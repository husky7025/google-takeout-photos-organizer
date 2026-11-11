import os
import sys
import subprocess
import webbrowser
import time

def check_requirements():
    try:
        import fastapi
        import uvicorn
        import pydantic
        import websockets
    except ImportError:
        print("[Notice] Installing required libraries...")
        req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])

def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:8000")

def main():
    check_requirements()
    
    # Auto open browser in background thread
    import threading
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("=" * 60)
    print("  Google Takeout Photo Organizer Server is running!")
    print("  Address: http://127.0.0.1:8000")
    print("  (Press Ctrl+C to stop)")
    print("=" * 60)
    print()

    import uvicorn
    # Run uvicorn server directly from python
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
