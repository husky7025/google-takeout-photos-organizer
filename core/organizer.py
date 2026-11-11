import os
import shutil
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import List, Callable, Optional, Set
from core.scanner import MediaItem
from core.exif_writer import apply_metadata_to_file

class OrganizerTask:
    def __init__(
        self,
        items: List[MediaItem],
        output_dir: str,
        action: str = "copy",  # "copy" or "move"
        write_exif: bool = True,
        standardize_name: bool = False,
        deduplicate: bool = True,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[dict], None]] = None
    ):
        self.items = items
        self.output_dir = output_dir
        self.action = action.lower()
        self.write_exif = write_exif
        self.standardize_name = standardize_name
        self.deduplicate = deduplicate
        self.max_workers = max(1, min(max_workers, 16))
        self.progress_callback = progress_callback
        self.is_cancelled = False
        self.seen_hashes: Set[str] = set()

    def cancel(self):
        self.is_cancelled = True

    def _process_single_item(self, item: MediaItem) -> dict:
        """Process one item: deduplicate, rename, copy/move, write exif."""
        res = {
            "filename": item.filename,
            "dest_path": "",
            "status": "processing",
            "message": ""
        }

        # 1. Deduplication check (Hash based)
        if self.deduplicate and not item.is_live_photo_video:
            h = item.get_hash()
            if h in self.seen_hashes:
                res["status"] = "dedup_skipped"
                res["message"] = f"내용 동일 중복 사진 건너뜀: {item.filename}"
                return res
            self.seen_hashes.add(h)

        # 2. Target Directory: output_dir / YYYY / YYYY-MM
        folder_year = item.target_year if item.target_year else "기타"
        folder_month = item.target_month if item.target_month else "기타"
        target_folder = os.path.join(self.output_dir, folder_year, folder_month)
        os.makedirs(target_folder, exist_ok=True)

        # 3. Determine Filename (Original or Standardized)
        ext = item.corrected_ext if (item.corrected_ext and item.original_ext != item.corrected_ext) else item.original_ext
        if not ext and item.corrected_ext:
            ext = item.corrected_ext

        if self.standardize_name and item.timestamp:
            dt = datetime.fromtimestamp(item.timestamp)
            date_prefix = dt.strftime("%Y%m%d_%H%M%S")
            # Clean stem of (1) or spaces
            stem, _ = os.path.splitext(item.filename)
            stem = stem.replace(" ", "_")
            if not stem.startswith(date_prefix):
                target_filename = f"{date_prefix}_{stem}{ext}"
            else:
                target_filename = f"{stem}{ext}"
        else:
            if item.corrected_ext and item.original_ext != item.corrected_ext:
                target_filename = item.filename + item.corrected_ext
            else:
                target_filename = item.filename

        dest_path = os.path.join(target_folder, target_filename)

        # 4. Check Smart Resume (Skip already completed in prior run)
        if os.path.exists(dest_path) and os.path.abspath(dest_path) != os.path.abspath(item.original_path):
            if os.path.getsize(dest_path) == item.size:
                res["status"] = "skipped"
                res["dest_path"] = dest_path
                res["message"] = f"이미 완료됨 (건너뜀): {os.path.basename(dest_path)}"
                return res

            # Same name but different file content -> rename to avoid collision
            base_name, f_ext = os.path.splitext(target_filename)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(target_folder, f"{base_name}_{counter}{f_ext}")
                counter += 1

        res["dest_path"] = dest_path

        # 5. Copy or Move
        try:
            if self.action == "move":
                shutil.move(item.original_path, dest_path)
            else:
                shutil.copy2(item.original_path, dest_path)

            # 6. Apply EXIF and Timestamp
            if self.write_exif and item.timestamp:
                meta = item.metadata
                apply_metadata_to_file(
                    dest_path,
                    timestamp=item.timestamp,
                    latitude=meta.get("latitude"),
                    longitude=meta.get("longitude"),
                    altitude=meta.get("altitude"),
                    description=meta.get("description")
                )

            res["status"] = "success"
            res["message"] = f"정리 완료: {os.path.basename(dest_path)}"
        except Exception as e:
            res["status"] = "error"
            res["message"] = str(e)

        return res

    def run(self):
        total = len(self.items)
        success_count = 0
        failed_count = 0
        skipped_count = 0
        dedup_count = 0
        processed_count = 0

        # Execute using ThreadPool for high speed batch throughput
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self._process_single_item, item) for item in self.items]

            for fut in futures:
                if self.is_cancelled:
                    if self.progress_callback:
                        self.progress_callback({
                            "event": "cancelled",
                            "message": "작업이 사용자에 의해 중단되었습니다."
                        })
                    break

                res = fut.result()
                processed_count += 1
                status = res["status"]

                if status == "success":
                    success_count += 1
                elif status == "skipped":
                    skipped_count += 1
                elif status == "dedup_skipped":
                    dedup_count += 1
                elif status == "error":
                    failed_count += 1

                percent = round((processed_count / total) * 100, 1)
                status_item = {
                    "index": processed_count,
                    "total": total,
                    "percent": percent,
                    "filename": res["filename"],
                    "dest_path": res["dest_path"],
                    "status": status,
                    "message": res["message"]
                }

                if self.progress_callback:
                    self.progress_callback({
                        "event": "progress",
                        "item": status_item,
                        "stats": {
                            "total": total,
                            "processed": processed_count,
                            "success": success_count,
                            "skipped": skipped_count,
                            "dedup_skipped": dedup_count,
                            "failed": failed_count,
                            "percent": percent
                        }
                    })

        if self.progress_callback and not self.is_cancelled:
            self.progress_callback({
                "event": "done",
                "stats": {
                    "total": total,
                    "processed": total,
                    "success": success_count,
                    "skipped": skipped_count,
                    "dedup_skipped": dedup_count,
                    "failed": failed_count,
                    "percent": 100
                }
            })


def cleanup_leftovers(source_dir: str) -> dict:
    """Removes orphan JSON files and empty directories in source_dir."""
    deleted_jsons = 0
    deleted_dirs = 0
    errors = []

    # 1. Delete JSON files in source_dir
    for dirpath, _, filenames in os.walk(source_dir, topdown=False):
        for f in filenames:
            if f.endswith('.json'):
                try:
                    os.remove(os.path.join(dirpath, f))
                    deleted_jsons += 1
                except Exception as e:
                    errors.append(str(e))

    # 2. Delete empty directories
    for dirpath, dirnames, filenames in os.walk(source_dir, topdown=False):
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
                deleted_dirs += 1
            except Exception as e:
                errors.append(str(e))

    return {
        "deleted_jsons": deleted_jsons,
        "deleted_dirs": deleted_dirs,
        "errors_count": len(errors)
    }
