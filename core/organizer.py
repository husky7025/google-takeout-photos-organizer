import os
import shutil
import asyncio
from typing import List, Callable, Optional
from core.scanner import MediaItem
from core.exif_writer import apply_metadata_to_file

class OrganizerTask:
    def __init__(
        self,
        items: List[MediaItem],
        output_dir: str,
        action: str = "copy",  # "copy" or "move"
        write_exif: bool = True,
        progress_callback: Optional[Callable[[dict], None]] = None
    ):
        self.items = items
        self.output_dir = output_dir
        self.action = action.lower()
        self.write_exif = write_exif
        self.progress_callback = progress_callback
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        total = len(self.items)
        success_count = 0
        failed_count = 0
        skipped_count = 0

        for idx, item in enumerate(self.items):
            if self.is_cancelled:
                if self.progress_callback:
                    self.progress_callback({
                        "event": "cancelled",
                        "message": "작업이 사용자에 의해 중단되었습니다."
                    })
                break

            # 1. Determine destination path: output_dir / YYYY / YYYY-MM / filename
            folder_year = item.target_year if item.target_year else "기타"
            folder_month = item.target_month if item.target_month else "기타"
            target_folder = os.path.join(self.output_dir, folder_year, folder_month)
            os.makedirs(target_folder, exist_ok=True)

            # Fix extension if it was missing/detected
            target_filename = item.filename
            if item.corrected_ext and item.original_ext != item.corrected_ext:
                target_filename = item.filename + item.corrected_ext

            dest_path = os.path.join(target_folder, target_filename)

            status_item = {
                "index": idx + 1,
                "total": total,
                "percent": round(((idx + 1) / total) * 100, 1),
                "filename": item.filename,
                "dest_path": dest_path,
                "status": "processing",
                "message": ""
            }

            try:
                # 2. Check if already processed (Smart Resume / Skip duplicate)
                if os.path.exists(dest_path) and os.path.abspath(dest_path) != os.path.abspath(item.original_path):
                    # If file size matches, it was already organized in previous run
                    if os.path.getsize(dest_path) == item.size:
                        skipped_count += 1
                        status_item["status"] = "skipped"
                        status_item["message"] = f"이미 완료됨 (건너뜀): {os.path.basename(dest_path)}"
                        if self.progress_callback:
                            self.progress_callback({
                                "event": "progress",
                                "item": status_item,
                                "stats": {
                                    "total": total,
                                    "processed": idx + 1,
                                    "success": success_count,
                                    "skipped": skipped_count,
                                    "failed": failed_count,
                                    "percent": status_item["percent"]
                                }
                            })
                        continue

                    # If file exists but size differs, avoid overwriting by renaming
                    base_name, ext = os.path.splitext(target_filename)
                    counter = 1
                    while os.path.exists(dest_path):
                        dest_path = os.path.join(target_folder, f"{base_name}_{counter}{ext}")
                        counter += 1
                    status_item["dest_path"] = dest_path

                # 3. Copy or Move
                if self.action == "move":
                    shutil.move(item.original_path, dest_path)
                else:
                    shutil.copy2(item.original_path, dest_path)

                # 4. Apply EXIF and Timestamp
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

                success_count += 1
                status_item["status"] = "success"
                status_item["message"] = f"정리 완료: {os.path.basename(dest_path)}"

            except Exception as e:
                failed_count += 1
                status_item["status"] = "error"
                status_item["message"] = str(e)

            if self.progress_callback:
                self.progress_callback({
                    "event": "progress",
                    "item": status_item,
                    "stats": {
                        "total": total,
                        "processed": idx + 1,
                        "success": success_count,
                        "skipped": skipped_count,
                        "failed": failed_count,
                        "percent": status_item["percent"]
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
                    "failed": failed_count,
                    "percent": 100
                }
            })
