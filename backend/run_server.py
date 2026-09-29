import os
import sys
import uvicorn

# Auto-configure PATH for FFmpeg, FFprobe & Tools
extra_paths = [
    r"C:\Program Files\Anas Media Downloader\_internal\bin",
    r"C:\Program Files\nodejs",
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin"
]
for p in extra_paths:
    if os.path.exists(p) and p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

if __name__ == "__main__":
    print("=" * 60)
    print("🎬 AUTOEXPLAINER AI SAAS — BACKEND SERVER STARTING")
    print("📡 FastAPI Swagger Docs: http://127.0.0.1:8000/docs")
    print("=" * 60)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
