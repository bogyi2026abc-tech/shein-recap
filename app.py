from pathlib import Path
from uuid import uuid4
import asyncio, os, subprocess

import edge_tts
import imageio_ffmpeg
from google import genai
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
UPLOADS, OUTPUTS, STATIC = BASE / "uploads", BASE / "outputs", BASE / "static"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
for folder in (UPLOADS, OUTPUTS, STATIC):
    folder.mkdir(exist_ok=True)

app = FastAPI(title="SHEIN RECAP", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
MAX_UPLOAD = 500 * 1024 * 1024
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
TRANSCRIBE_MODEL = os.getenv("GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe")

def ai_client():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise HTTPException(503, "GEMINI_API_KEY ကို Render Environment မှာ ထည့်ပေးပါ။ Google AI Studio မှာ အခမဲ့ API Key ရယူနိုင်ပါတယ်။")
    return genai.Client(api_key=key)

def run_cmd(args):
    if args and args[0] == "ffmpeg":
        args = [FFMPEG, *args[1:]]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        raise HTTPException(503, "လိုအပ်တဲ့ video processing program မတွေ့ပါ။")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Video processing အချိန်ကျော်သွားပါတယ်။")
    if p.returncode:
        raise HTTPException(500, (p.stderr or "Processing failed")[-1200:])
    return p.stdout

def get_audio(video: Path, out: Path):
    run_cmd(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)])
    return out

def transcribe(audio: Path):
    client = ai_client()
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(audio))
        response = client.interactions.create(
            model=TRANSCRIBE_MODEL,
            input=[
                {"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type}
            ]
        )
        return (response.output_text or "").strip()
    except Exception as exc:
        raise HTTPException(502, f"အသံကို စာသားပြောင်းရာမှာ Gemini API အမှားဖြစ်နေပါတယ်: {str(exc)[:500]}")
    finally:
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

def make_script(transcript: str, style: str = "စိတ်ဝင်စားဖွယ်၊ သဘာဝကျတဲ့ စကားပြောဟန်"):
    prompt = f"""အောက်ပါ ရုပ်ရှင်ဇာတ်လမ်း transcript ကို မြန်မာဘာသာနဲ့ TikTok movie recap narration အဖြစ် ပြန်ရေးပါ။
လိုအပ်ချက်များ - အစမှာ အားကောင်းတဲ့ hook ပါစေ၊ ဇာတ်လမ်းအစဉ်လိုက်နဲ့ အဓိကအချက်တွေ မပျောက်စေပါနဲ့၊ တိုက်ရိုက်ဘာသာပြန်သလို မဖြစ်ဘဲ မြန်မာလူတစ်ယောက် ပါးစပ်က ပြောပြနေသလို သဘာဝကျပြီး ချောမွေ့ပါစေ၊ နောက်ဆုံးမှာ စိတ်ဝင်စားစရာ ending hook ထည့်ပါ၊ အင်္ဂလိပ်စကားလုံးတွေ မလိုအပ်ဘဲ မသုံးပါနဲ့။
ဟန်ပန်: {style}
Transcript:
{transcript[:90000]}"""
    try:
        response = ai_client().interactions.create(
            model=MODEL,
            input="သင်သည် မြန်မာဘာသာဖြင့် ရုပ်ရှင်ဇာတ်လမ်းများကို သဘာဝကျကျ ပြောပြနိုင်သော recap စာရေးဆရာဖြစ်သည်။\n\n" + prompt
        )
        return (response.output_text or "").strip()
    except Exception as exc:
        raise HTTPException(502, f"မြန်မာ Recap ရေးရာမှာ Gemini API အမှားဖြစ်နေပါတယ်: {str(exc)[:500]}")

@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "app": "SHEIN RECAP", "version": "0.3.0", "ffmpeg": Path(FFMPEG).is_file(), "ai_ready": bool(os.getenv("GEMINI_API_KEY")), "ai_provider": "Google Gemini Free Tier", "tts": "Microsoft Edge Burmese voices"}

@app.post("/api/upload")
async def upload_video(video: UploadFile = File(...)):
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTS:
        raise HTTPException(400, "MP4, MOV, MKV, WEBM ဖိုင်သာ လက်ခံပါတယ်။")
    file_id = uuid4().hex
    destination = UPLOADS / f"{file_id}{suffix}"
    size = 0
    try:
        with destination.open("wb") as out:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "Video ဖိုင် 500MB ထက် မကြီးရပါ။")
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"ok": True, "file_id": file_id, "filename": video.filename, "size": size}

@app.post("/api/recap")
async def create_recap(youtube_url: str = Form(""), file_id: str = Form(""), style: str = Form("သဘာဝကျတဲ့ စကားပြောဟန်")):
    work_id = uuid4().hex
    work = OUTPUTS / work_id
    work.mkdir()
    if file_id:
        matches = list(UPLOADS.glob(file_id + ".*"))
        if not matches:
            raise HTTPException(404, "တင်ထားတဲ့ Video ကို ရှာမတွေ့ပါ။ ပြန်တင်ပေးပါ။")
        audio = get_audio(matches[0], work / "audio.mp3")
    elif youtube_url:
        if not youtube_url.strip().lower().startswith(("https://youtube.com/", "http://youtube.com/", "https://www.youtube.com/", "http://www.youtube.com/", "https://youtu.be/", "http://youtu.be/")):
            raise HTTPException(400, "YouTube link မှန်ကန်စွာ ထည့်ပေးပါ။")
        downloaded = work / "source.%(ext)s"
        run_cmd(["yt-dlp", "--no-playlist", "--ffmpeg-location", FFMPEG, "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "-o", str(downloaded), youtube_url.strip()])
        audios = list(work.glob("source.*"))
        if not audios:
            raise HTTPException(500, "YouTube အသံကို ရယူမရပါ။")
        audio = audios[0]
    else:
        raise HTTPException(400, "YouTube link သို့မဟုတ် Upload လုပ်ထားတဲ့ Video တစ်ခု ရွေးပေးပါ။")
    transcript = transcribe(audio)
    if not transcript:
        raise HTTPException(422, "အသံထဲက စကားကို မဖတ်နိုင်ပါ။")
    script = make_script(transcript, style)
    (work / "transcript.txt").write_text(transcript, encoding="utf-8")
    (work / "recap.txt").write_text(script, encoding="utf-8")
    return {"ok": True, "job_id": work_id, "transcript": transcript, "script": script}

@app.post("/api/speech")
async def create_speech(script: str = Form(...), voice: str = Form("my-MM-ThihaNeural"), speed: float = Form(1.0), tone: str = Form("သဘာဝကျပြီး ရှင်းလင်းသော အသံ")):
    if not script.strip():
        raise HTTPException(400, "အသံဖန်တီးရန် စာသားထည့်ပေးပါ။")
    voices = {"my-MM-ThihaNeural", "my-MM-NilarNeural"}
    if voice not in voices:
        raise HTTPException(400, "ရွေးထားတဲ့ မြန်မာအသံအမျိုးအစား မမှန်ပါ။")
    if not 0.7 <= speed <= 1.3:
        raise HTTPException(400, "အသံအမြန်နှုန်းကို 0.7 မှ 1.3 အတွင်းထားပါ။")
    output = OUTPUTS / f"{uuid4().hex}.mp3"
    rate = f"{round((speed - 1) * 100):+d}%"
    try:
        communicate = edge_tts.Communicate(script[:12000], voice, rate=rate)
        await communicate.save(str(output))
    except Exception as exc:
        raise HTTPException(502, f"အခမဲ့ မြန်မာအသံဖန်တီးရာမှာ ချိတ်ဆက်မှုအမှားဖြစ်နေပါတယ်: {str(exc)[:400]}")
    return {"ok": True, "audio_url": f"/api/file/{output.name}"}

@app.get("/api/file/{filename}")
async def get_file(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(400, "Invalid filename")
    target = OUTPUTS / filename
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(target)

@app.post("/api/thumbnail")
async def thumbnail(file_id: str = Form(...), second: float = Form(1.0)):
    matches = list(UPLOADS.glob(file_id + ".*"))
    if not matches:
        raise HTTPException(404, "Video မတွေ့ပါ။")
    output = OUTPUTS / f"{uuid4().hex}.jpg"
    run_cmd(["ffmpeg","-y","-ss",str(max(0,second)),"-i",str(matches[0]),"-frames:v","1","-vf","scale=1080:-2",str(output)])
    return {"ok": True, "image_url": f"/api/file/{output.name}"}

@app.post("/api/export")
async def export_video(file_id: str = Form(...), blur_x: int = Form(-1), blur_y: int = Form(-1), blur_w: int = Form(0), blur_h: int = Form(0), blur_start: float = Form(0), blur_end: float = Form(0)):
    matches = list(UPLOADS.glob(file_id + ".*"))
    if not matches:
        raise HTTPException(404, "Video မတွေ့ပါ။")
    source = matches[0]
    output = OUTPUTS / f"{uuid4().hex}_vertical.mp4"
    base_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if blur_x >= 0 and blur_y >= 0 and blur_w > 0 and blur_h > 0 and blur_end > blur_start:
        graph = f"[0:v]{base_filter},split[base][tmp];[tmp]crop={blur_w}:{blur_h}:{blur_x}:{blur_y},boxblur=20:2[blur];[base][blur]overlay={blur_x}:{blur_y}:enable='between(t,{blur_start},{blur_end})'[outv]"
        run_cmd(["ffmpeg","-y","-i",str(source),"-filter_complex",graph,"-map","[outv]","-map","0:a?","-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(output)])
    else:
        run_cmd(["ffmpeg","-y","-i",str(source),"-vf",base_filter,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(output)])
    return {"ok": True, "video_url": f"/api/file/{output.name}"}
