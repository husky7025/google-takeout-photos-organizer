import os
import sys
import uuid
import threading
import asyncio
from typing import Dict, Optional, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# Add current directory to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.scanner import scan_takeout_directory, MediaItem
from core.organizer import OrganizerTask, cleanup_leftovers
from core.exif_writer import get_exiftool_path

app = FastAPI(title="Google Takeout Photo Organizer")

# Mount static directory
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# In-memory state
current_scan_items: List[MediaItem] = []
current_scan_stats: dict = {}
active_task: Optional[OrganizerTask] = None
latest_progress: dict = {"event": "idle"}
event_loop = None

class ScanRequest(BaseModel):
    source_dir: str

class StartRequest(BaseModel):
    output_dir: str
    action: str = "copy"
    write_exif: bool = True
    standardize_name: bool = False
    deduplicate: bool = True
    threads: int = 4

class CleanupRequest(BaseModel):
    source_dir: str

@app.on_event("startup")
async def startup_event():
    global event_loop
    event_loop = asyncio.get_event_loop()

@app.get("/")
def get_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/progress")
def get_progress():
    return latest_progress

@app.post("/api/browse-folder")
def api_browse_folder(data: dict = None):
    initial = (data or {}).get("initial", "")
    folder_path = ""

    def ask_folder():
        nonlocal folder_path
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        res = filedialog.askdirectory(initialdir=initial or None, title="폴더 선택")
        root.destroy()
        folder_path = res

    # Run GUI in a thread to keep FastAPI responsive
    t = threading.Thread(target=ask_folder)
    t.start()
    t.join(timeout=60)

    if folder_path:
        folder_path = os.path.normpath(folder_path)
    return {"folder": folder_path}

@app.get("/api/exiftool-status")
def get_exiftool_status():
    tool_path = get_exiftool_path()
    version = None
    if tool_path:
        import subprocess
        try:
            p = subprocess.run([tool_path, "-ver"], stdout=subprocess.PIPE, text=True, timeout=5)
            version = p.stdout.strip()
        except Exception:
            pass

    # Default suggested directories
    default_source = os.path.abspath(os.path.join(BASE_DIR, "..", "Google 포토"))
    default_output = os.path.abspath(os.path.join(BASE_DIR, "..", "Google_Photos_Organized"))

    return {
        "available": tool_path is not None,
        "path": tool_path,
        "version": version,
        "default_source": default_source if os.path.exists(default_source) else "",
        "default_output": default_output
    }

@app.post("/api/scan")
def api_scan(req: ScanRequest):
    global current_scan_items, current_scan_stats
    source = req.source_dir.strip()
    if not os.path.isdir(source):
        return JSONResponse(status_code=400, content={"error": f"폴더를 찾을 수 없습니다: {source}"})

    try:
        items, stats = scan_takeout_directory(source)
        current_scan_items = items
        current_scan_stats = stats
        return {
            "stats": stats,
            "items": [it.to_dict() for it in items]
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/start")
def api_start(req: StartRequest):
    global active_task
    if not current_scan_items:
        return JSONResponse(status_code=400, content={"error": "먼저 폴더를 스캔하세요."})

    job_id = str(uuid.uuid4())

    def broadcast_progress(msg: dict):
        global latest_progress
        latest_progress = msg

    task = OrganizerTask(
        items=current_scan_items,
        output_dir=req.output_dir.strip(),
        action=req.action,
        write_exif=req.write_exif,
        standardize_name=req.standardize_name,
        deduplicate=req.deduplicate,
        max_workers=req.threads,
        progress_callback=broadcast_progress
    )
    active_task = task

    # Run in background thread
    thread = threading.Thread(target=task.run, daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "started"}

@app.post("/api/cleanup-leftovers")
def api_cleanup_leftovers(req: CleanupRequest):
    source = req.source_dir.strip()
    if not os.path.isdir(source):
        return JSONResponse(status_code=400, content={"error": f"폴더를 찾을 수 없습니다: {source}"})
    try:
        res = cleanup_leftovers(source)
        return res
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/cancel")
def api_cancel():
    global active_task
    if active_task:
        active_task.cancel()
        return {"status": "cancelled"}
    return {"status": "no_active_task"}

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    active_websockets[job_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if job_id in active_websockets:
            del active_websockets[job_id]
