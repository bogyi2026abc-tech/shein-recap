from pathlib import Path
from uuid import uuid4
import json, os, re, shutil, subprocess

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
OUTPUTS = BASE / "outputs"
STATIC = BASE / "static"
for folder in (UPLOADS, OUTPUTS, STATIC):
    folder.mkdir(exist_ok=True)

app = FastAPI(title="SHEIN RECAP", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
MAX_UPLOAD = 500 * 1024 * 1024
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}

def client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(503, "OPENAI_API_KEY ကို Render Environment မှာ ထည့်ပေးပါ။")
    return OpenAI(api_key=key)

def run_cmd(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        raise HTTPException(503, "Server မှာ FFmpeg မရှိသေးပါ။ Render မှာ FFmpeg ထည့်သွင်းရန်လိုပါတယ်။")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Video processing အချိန်ကျော်သွားပါတယ်။")
    if p.returncode:
        raise HTTPException(500, (p.stderr or "Processing failed")[-1200:])
    return p.stdout

def get_audio(video: Path, out: Path):
    run_cmd(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(out)])
    return out

def transcribe(audio: Path):
    if audio.stat().st_size > 24 * 1024 * 1024:
        smaller = audio.with_name(audio.stem + "_small.mp3")
        run_cmd(["ffmpeg", "-y", "-i", str(audio), "-b:a", "48k", "-ac", "1", str(smaller)])
        audio = smaller
    with audio.open("rb") as f:
        result = client().audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=f)
    return result.text

def make_script(transcript: str, style: str = "စိတ်ဝင်စားဖွယ်၊ သဘာဝကျတဲ့ စကားပြောဟန်"):
    prompt = f"""အောက်ပါ ရုပ်ရှင်ဇာတ်လမ်း transcript ကို မြန်မာဘာသာနဲ့ TikTok movie recap narration အဖြစ် ပြန်ရေးပါ။
လိုအပ်ချက်များ - အစမှာ အားကောင်းတဲ့ hook ပါစေ၊ ဇာတ်လမ်းအစဉ်လိုက်နဲ့ အဓိကအချက်တွေ မပျောက်စေပါနဲ့၊ တိုက်ရိုက်ဘာသာပြန်သလို မဖြစ်ဘဲ မြန်မာလူတစ်ယောက် ပြောပြနေသလို သဘာဝကျပါစေ၊ နောက်ဆုံးမှာ စိတ်ဝင်စားစရာ ending hook ထည့်ပါ၊ အင်္ဂလိပ်စကားလုံးတွေ မလိုအပ်ဘဲ မသုံးပါနဲ့။
ဟန်ပန်: {style}
Transcript:
{transcript[:90000]}"""
    response = client().chat.completions.create(
        model=os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        messages=[{"role":"system","content":"သင်သည် မြန်မာဘာသာဖြင့် ရုပ်ရှင်ဇာတ်လမ်းများကို သဘာဝကျကျ ပြောပြနိုင်သော recap စာရေးဆရာဖြစ်သည်။"},{"role":"user","content":prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content or ""

@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "app": "SHEIN RECAP", "version": "0.2.0", "ffmpeg": shutil.which("ffmpeg") is not None, "ai_ready": bool(os.getenv("OPENAI_API_KEY"))}

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
        video = matches[0]
        audio = get_audio(video, work / "audio.mp3")
    elif youtube_url:
        if not re.match(r"^https?://(www\\.)?(youtube\\.com|youtu\\.be)/", youtube_url.strip()):
            raise HTTPException(400, "YouTube link မှန်ကန်စွာ ထည့်ပေးပါ။")
        downloaded = work / "source.%(ext)s"
        run_cmd(["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "-o", str(downloaded), youtube_url.strip()])
        audios = list(work.glob("source.*"))
        if not audios:
            raise HTTPException(500, "YouTube အသံကို ရယူမရပါ။ Video ရဲ့ subtitle ရှိ/မရှိ စစ်ဆေးပါ။")
        audio = audios[0]
    else:
        raise HTTPException(400, "YouTube link သို့မဟုတ် Upload လုပ်ထားတဲ့ Video တစ်ခု ရွေးပေးပါ။")
    transcript = transcribe(audio)
    if not transcript.strip():
        raise HTTPException(422, "အသံထဲက စကားကို မဖတ်နိုင်ပါ။")
    script = make_script(transcript, style)
    (work / "transcript.txt").write_text(transcript, encoding="utf-8")
    (work / "recap.txt").write_text(script, encoding="utf-8")
    return {"ok": True, "job_id": work_id, "transcript": transcript, "script": script}

@app.post("/api/speech")
async def create_speech(script: str = Form(...), voice: str = Form("onyx"), speed: float = Form(1.0), tone: str = Form("သဘာဝကျပြီး ရှင်းလင်းသော အသံ")):
    if not script.strip():
        raise HTTPException(400, "အသံဖန်တီးရန် စာသားထည့်ပေးပါ။")
    if voice not in {"alloy","ash","coral","echo","fable","onyx","nova","sage","shimmer"}:
        raise HTTPException(400, "ရွေးထားတဲ့ အသံအမျိုးအစား မမှန်ပါ။")
    if not 0.7 <= speed <= 1.3:
        raise HTTPException(400, "အသံအမြန်နှုန်းကို 0.7 မှ 1.3 အတွင်းထားပါ။")
    output = OUTPUTS / f"{uuid4().hex}.mp3"
    speech = client().audio.speech.create(model="gpt-4o-mini-tts", voice=voice, input=script[:12000], speed=speed, instructions=tone)
    speech.stream_to_file(output)
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
