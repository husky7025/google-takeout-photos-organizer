import os
import re
import glob
from typing import Dict, List, Optional, Tuple
from core.metadata import detect_extension_by_magic, parse_metadata_json, MEDIA_EXTENSIONS

class MediaItem:
    def __init__(self, original_path: str, detected_ext: Optional[str] = None):
        self.original_path = original_path
        self.filename = os.path.basename(original_path)
        self.size = os.path.getsize(original_path) if os.path.exists(original_path) else 0
        _, ext = os.path.splitext(self.filename)
        self.original_ext = ext
        self.corrected_ext = detected_ext or ext
        self.json_path: Optional[str] = None
        self.metadata: dict = {}
        self.timestamp: Optional[int] = None
        self.target_year: str = "Unknown"
        self.target_month: str = "Unknown"
        self.is_live_photo_video = False
        self.live_photo_pair: Optional['MediaItem'] = None
        self.file_hash: Optional[str] = None

    def get_hash(self) -> str:
        """Calculate fast partial or full hash of the file for duplicate detection."""
        if self.file_hash:
            return self.file_hash
        import hashlib
        h = hashlib.md5()
        # For fast comparison, if file is huge, hash size + first 64KB + last 64KB
        try:
            with open(self.original_path, 'rb') as f:
                if self.size <= 256 * 1024:
                    h.update(f.read())
                else:
                    h.update(str(self.size).encode())
                    h.update(f.read(64 * 1024))
                    f.seek(-64 * 1024, os.SEEK_END)
                    h.update(f.read(64 * 1024))
            self.file_hash = h.hexdigest()
        except Exception:
            self.file_hash = f"{self.size}_{self.filename}"
        return self.file_hash

    def to_dict(self):
        return {
            "original_path": self.original_path,
            "filename": self.filename,
            "size": self.size,
            "original_ext": self.original_ext,
            "corrected_ext": self.corrected_ext,
            "has_json": self.json_path is not None,
            "timestamp": self.timestamp,
            "target_year": self.target_year,
            "target_month": self.target_month,
            "is_live_photo_video": self.is_live_photo_video,
            "has_geo": bool(self.metadata.get('latitude'))
        }


def find_json_for_media(media_filename: str, json_map: Dict[str, str]) -> Optional[str]:
    """
    Find matching JSON metadata for a media filename.
    Handles Google Takeout naming variants:
      1. IMG_0758(1).JPG -> IMG_0758.JPG.supplemental-metadata(1).json
      2. IMG_0758(1).JPG -> IMG_0758(1).JPG.supplemental-metadata.json
      3. IMG_0758.JPG -> IMG_0758.JPG.supplemental-metadata.json / suppl.json
      4. Standard <name>.json
    """
    lower_map = {k.lower(): v for k, v in json_map.items()}
    lower_media = media_filename.lower()
    stem, ext = os.path.splitext(media_filename)
    lower_stem = stem.lower()

    # Check for (N) duplicate pattern in stem: e.g. "IMG_0758(1)" -> base="IMG_0758", idx="1"
    idx_match = re.search(r'\((\d+)\)$', stem)
    if idx_match:
        idx = idx_match.group(1)
        base_stem = stem[:idx_match.start()]
        # Variants:
        # base_stem + ext + ".supplemental-metadata(" + idx + ").json"
        v1 = f"{base_stem}{ext}.supplemental-metadata({idx}).json".lower()
        v2 = f"{base_stem}{ext}.suppl({idx}).json".lower()
        v3 = f"{base_stem}.supplemental-metadata({idx}).json".lower()
        v4 = f"{base_stem}({idx}){ext}.supplemental-metadata.json".lower()
        for cand in [v1, v2, v3, v4]:
            if cand in lower_map:
                return lower_map[cand]

    candidates = [
        f"{lower_media}.supplemental-metadata.json",
        f"{lower_media}.suppl.json",
        f"{lower_media}.json",
        f"{lower_stem}.supplemental-metadata.json",
        f"{lower_stem}.suppl.json",
        f"{lower_stem}.json",
    ]

    for cand in candidates:
        if cand in lower_map:
            return lower_map[cand]

    # Look for partial matches if Takeout truncated long names (>46 chars) or truncated trailing chars
    clean_stem = re.sub(r'[_\-\s\(\)\d]+$', '', lower_stem)
    for key, path in lower_map.items():
        if key.startswith(lower_media[:30]) or (clean_stem and len(clean_stem) >= 15 and key.startswith(clean_stem)):
            return path

    return None


def scan_takeout_directory(root_dir: str) -> Tuple[List[MediaItem], Dict[str, int]]:
    """Scan the root directory recursively, build items, pair JSONs, and pair Live Photos."""
    media_items: List[MediaItem] = []
    json_map_by_dir: Dict[str, Dict[str, str]] = {}
    stats = {
        "total_files": 0,
        "media_files": 0,
        "json_files": 0,
        "matched_json": 0,
        "extension_fixed": 0,
        "live_photos": 0
    }

    # Step 1: Collect files by directory
    for dirpath, _, filenames in os.walk(root_dir):
        if not filenames:
            continue
        stats["total_files"] += len(filenames)
        dir_jsons = {}
        for f in filenames:
            if f.endswith('.json'):
                stats["json_files"] += 1
                dir_jsons[f] = os.path.join(dirpath, f)
        json_map_by_dir[dirpath] = dir_jsons

        for f in filenames:
            if f.endswith('.json'):
                continue
            
            full_path = os.path.join(dirpath, f)
            _, ext = os.path.splitext(f)
            detected_ext = None
            if not ext:
                detected_ext = detect_extension_by_magic(full_path)
                if detected_ext:
                    stats["extension_fixed"] += 1
                    ext = detected_ext
            
            # Keep if recognized media or repaired
            if ext.lower() in MEDIA_EXTENSIONS or detected_ext:
                item = MediaItem(full_path, detected_ext)
                media_items.append(item)
                stats["media_files"] += 1

    # Step 2: Match JSON metadata
    for item in media_items:
        dirpath = os.path.dirname(item.original_path)
        dir_jsons = json_map_by_dir.get(dirpath, {})
        matched_json = find_json_for_media(item.filename, dir_jsons)
        if matched_json:
            item.json_path = matched_json
            stats["matched_json"] += 1
            meta = parse_metadata_json(matched_json)
            item.metadata = meta
            if meta.get('timestamp'):
                item.timestamp = meta['timestamp']

        # Fallback timestamp from file system if no json timestamp
        if not item.timestamp:
            try:
                item.timestamp = int(os.path.getmtime(item.original_path))
            except Exception:
                pass

        # Compute target Year & Month
        if item.timestamp:
            import datetime
            dt = datetime.datetime.fromtimestamp(item.timestamp)
            item.target_year = str(dt.year)
            item.target_month = f"{dt.year}-{dt.month:02d}"

    # Step 3: Match iOS Live Photos (MOV + HEIC/JPG)
    items_by_stem_dir: Dict[Tuple[str, str], List[MediaItem]] = {}
    for item in media_items:
        stem, _ = os.path.splitext(item.filename)
        dirpath = os.path.dirname(item.original_path)
        items_by_stem_dir.setdefault((dirpath, stem.lower()), []).append(item)

    for (dirpath, stem_lower), group in items_by_stem_dir.items():
        mov_items = [it for it in group if (it.corrected_ext or it.original_ext).lower() == '.mov']
        photo_items = [it for it in group if (it.corrected_ext or it.original_ext).lower() in ['.heic', '.jpg', '.jpeg', '.dng', '.png']]
        if mov_items and photo_items:
            for mov in mov_items:
                mov.is_live_photo_video = True
                mov.live_photo_pair = photo_items[0]
                # Inherit timestamp and target folder from photo if missing
                if photo_items[0].timestamp and not mov.json_path:
                    mov.timestamp = photo_items[0].timestamp
                    mov.target_year = photo_items[0].target_year
                    mov.target_month = photo_items[0].target_month
            stats["live_photos"] += len(mov_items)

    return media_items, stats
