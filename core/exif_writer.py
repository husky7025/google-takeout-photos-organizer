import os
import subprocess
import shutil
from datetime import datetime, timezone
from typing import Optional, List, Dict

# Candidate paths for ExifTool on Windows
POSSIBLE_EXIFTOOL_PATHS = [
    r"C:\Users\유재서\AppData\Local\Programs\ExifTool\ExifTool.exe",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "exiftool.exe"),
    "exiftool.exe",
    "exiftool"
]

def get_exiftool_path() -> Optional[str]:
    """Find available ExifTool executable."""
    for p in POSSIBLE_EXIFTOOL_PATHS:
        if os.path.isabs(p) and os.path.exists(p):
            return p
        which_p = shutil.which(p)
        if which_p and os.path.exists(which_p):
            return which_p
    return None

def apply_metadata_to_file(
    filepath: str,
    timestamp: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    altitude: Optional[float] = None,
    description: Optional[str] = None
) -> Dict[str, any]:
    """
    Applies EXIF tags via ExifTool and syncs Windows file modification/creation time.
    """
    res = {"exif_written": False, "filetime_synced": False, "error": None}
    
    # 1. Update OS File Times (atime and mtime)
    if timestamp:
        try:
            os.utime(filepath, (timestamp, timestamp))
            res["filetime_synced"] = True
        except Exception as e:
            res["error"] = f"utime error: {e}"

    # 2. Write EXIF/QuickTime tags using ExifTool
    exiftool = get_exiftool_path()
    if not exiftool:
        return res

    cmd = [exiftool, "-overwrite_original", "-charset", "filename=utf8"]
    
    if timestamp:
        # Format: "YYYY:MM:DD HH:MM:SS"
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        dt_str = dt.strftime("%Y:%m:%d %H:%M:%S")
        cmd.extend([
            f"-AllDates={dt_str}",
            f"-QuickTime:CreateDate={dt_str}",
            f"-QuickTime:ModifyDate={dt_str}",
            f"-FileCreateDate={dt_str}",
            f"-FileModifyDate={dt_str}"
        ])

    if latitude is not None and longitude is not None:
        lat_ref = "N" if latitude >= 0 else "S"
        lon_ref = "E" if longitude >= 0 else "W"
        cmd.extend([
            f"-GPSLatitude={abs(latitude)}",
            f"-GPSLatitudeRef={lat_ref}",
            f"-GPSLongitude={abs(longitude)}",
            f"-GPSLongitudeRef={lon_ref}",
            f"-QuickTime:GPSCoordinates={latitude},{longitude}"
        ])
        if altitude is not None:
            cmd.extend([
                f"-GPSAltitude={abs(altitude)}",
                f"-GPSAltitudeRef={0 if altitude >= 0 else 1}"
            ])

    if description:
        cmd.extend([
            f"-Description={description}",
            f"-ImageDescription={description}",
            f"-Caption-Abstract={description}"
        ])

    cmd.append(filepath)

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if proc.returncode == 0:
            res["exif_written"] = True
        else:
            res["error"] = proc.stderr or proc.stdout
    except Exception as e:
        res["error"] = str(e)

    # Re-apply utime because exiftool might touch mtime
    if timestamp:
        try:
            os.utime(filepath, (timestamp, timestamp))
        except Exception:
            pass

    return res
