import os
import sys
import time
import threading
import multiprocessing
import urllib.request
import webview

# Auto-configure system paths for FFmpeg & dependencies
extra_paths = [
    r"C:\Program Files\Anas Media Downloader\_internal\bin",
    r"C:\Program Files\nodejs",
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin"
]
for p in extra_paths:
    if os.path.exists(p) and p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, 'backend')
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

def is_server_online():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False

def run_fastapi():
    try:
        import uvicorn
        from app.main import app
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")
    except Exception as e:
        print(f"[Desktop Server Notice] {e}")

def wait_for_server():
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False

if __name__ == '__main__':
    multiprocessing.freeze_support()

    # Start FastAPI server if not already active
    if not is_server_online():
        server_thread = threading.Thread(target=run_fastapi, daemon=True)
        server_thread.start()
        wait_for_server()

    # Launch native standalone window (No browser tabs, no URL bar, zero terminal window)
    window = webview.create_window(
        title="AutoExplainer AI — Viral Movie & Drama Recap Studio",
        url="http://127.0.0.1:8000/",
        width=1420,
        height=900,
        min_size=(1050, 700),
        text_select=True,
        zoomable=True
    )

    # Start GUI loop (blocks until user clicks the 'X' button to close)
    webview.start()

    # Clean shutdown
    sys.exit(0)
