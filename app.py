from pathlib import Path
from uuid import uuid4
import os
import shutil

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="SHEIN RECAP", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def home():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "app": "SHEIN RECAP", "version": "0.1.0"}

@app.post("/api/upload")
async def upload_video(video: UploadFile = File(...)):
    allowed = {".mp4", ".mov", ".mkv", ".webm"}
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="MP4, MOV, MKV, or WEBM video only.")
    file_id = uuid4().hex
    destination = UPLOAD_DIR / f"{file_id}{suffix}"
    with destination.open("wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
    return {"ok": True, "file_id": file_id, "filename": video.filename, "size": destination.stat().st_size}

@app.post("/api/recap")
async def create_recap(
    youtube_url: str = Form(""),
    language: str = Form("မြန်မာ"),
):
    if not youtube_url.strip():
        raise HTTPException(status_code=400, detail="YouTube link ထည့်ပေးပါ။")
    # Recap generation is intentionally staged until transcript extraction
    # and the selected AI provider are configured.
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="AI API key မချိတ်ရသေးပါ။ Render Environment မှာ OPENAI_API_KEY ထည့်ပါ။")
    raise HTTPException(status_code=501, detail="AI transcript and recap pipeline is the next implementation step.")

