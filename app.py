from pathlib import Path
from uuid import uuid4
import asyncio, json, os, re, subprocess, time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
UPLOADS, OUTPUTS, STATIC = BASE / "uploads", BASE / "outputs", BASE / "static"
FFMPEG = None

def ffmpeg_path():
    global FFMPEG
    if FFMPEG is None:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return FFMPEG
for folder in (UPLOADS, OUTPUTS, STATIC):
    folder.mkdir(exist_ok=True)

app = FastAPI(title="SHEIN RECAP", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
MAX_UPLOAD = 500 * 1024 * 1024
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
TRANSCRIBE_MODEL = os.getenv("GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe")

def ai_client():
    from google import genai
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise HTTPException(503, "GEMINI_API_KEY ကို Render Environment မှာ ထည့်ပေးပါ။ Google AI Studio မှာ အခမဲ့ API Key ရယူနိုင်ပါတယ်။")
    return genai.Client(api_key=key)

def run_cmd(args):
    if args and args[0] == "ffmpeg":
        args = [ffmpeg_path(), *args[1:]]
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
    run_cmd(["ffmpeg", "-y", "-threads", "0", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(out)])
    return out

def _is_temporary_ai_error(exc):
    message = str(exc).upper()
    return any(token in message for token in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL", "TIMEOUT", "DEADLINE"))

def transcribe(audio: Path):
    # Upload the audio once, then reuse it for the primary model and one fallback.
    models = []
    for model in (TRANSCRIBE_MODEL, os.getenv("GEMINI_TRANSCRIBE_FALLBACK_MODEL", "gemini-3.5-flash")):
        if model and model not in models:
            models.append(model)
    errors = []
    client = ai_client()
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(audio))
        for model in models:
            for attempt, delay in enumerate((0, 2), start=1):
                if delay:
                    time.sleep(delay)
                try:
                    response = client.models.generate_content(model=model, contents=[
                        uploaded,
                        "Transcribe all spoken words accurately in the original language. Detect the spoken language automatically. Return only the transcript."
                    ])
                    transcript = (response.text or "").strip()
                    if transcript:
                        return transcript
                    errors.append(f"{model}: empty transcript")
                    break
                except Exception as exc:
                    errors.append(f"{model} attempt {attempt}: {str(exc)[:180]}")
                    if not _is_temporary_ai_error(exc):
                        break
    except Exception as exc:
        errors.append(f"audio upload: {str(exc)[:180]}")
    finally:
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
        try:
            client.close()
        except Exception:
            pass
    details = " | ".join(errors[-4:])
    raise HTTPException(502, f"အသံကို စာသားပြောင်းရာမှာ Gemini မော်ဒယ်များ မရနိုင်သေးပါ: {details[:650]}")


def make_script(transcript: str, style: str = "စိတ်ဝင်စားဖွယ်၊ သဘာဝကျတဲ့ စကားပြောဟန်"):
    prompt = f"""အောက်ပါ ရုပ်ရှင်ဇာတ်လမ်း transcript ကို မြန်မာဘာသာနဲ့ TikTok movie recap narration အဖြစ် ပြန်ရေးပါ။
လိုအပ်ချက်များ - အစမှာ အားကောင်းတဲ့ hook ပါစေ၊ ဇာတ်လမ်းအစဉ်လိုက်နဲ့ အဓိကအချက်တွေ မပျောက်စေပါနဲ့၊ တိုက်ရိုက်ဘာသာပြန်သလို မဖြစ်ဘဲ မြန်မာလူတစ်ယောက် ပါးစပ်က ပြောပြနေသလို သဘာဝကျပြီး ချောမွေ့ပါစေ၊ နောက်ဆုံးမှာ စိတ်ဝင်စားစရာ ending hook ထည့်ပါ၊ အင်္ဂလိပ်စကားလုံးတွေ မလိုအပ်ဘဲ မသုံးပါနဲ့။
ဟန်ပန်: {style}
Transcript:
{transcript[:90000]}"""
    prompt_text = "သင်သည် မြန်မာဘာသာဖြင့် ရုပ်ရှင်ဇာတ်လမ်းများကို သဘာဝကျကျ ပြောပြနိုင်သော recap စာရေးဆရာဖြစ်သည်။\n\n" + prompt
    models = []
    for model in (MODEL, os.getenv("GEMINI_RECAP_FALLBACK_MODEL", "gemini-3.8-flash")):
        if model and model not in models:
            models.append(model)
    errors = []
    client = ai_client()
    try:
        for model in models:
            for attempt, delay in enumerate((0, 2), start=1):
                if delay:
                    time.sleep(delay)
                try:
                    response = client.models.generate_content(model=model, contents=prompt_text)
                    script = (response.text or "").strip()
                    if script:
                        return script
                    errors.append(f"{model}: empty response")
                    break
                except Exception as exc:
                    errors.append(f"{model} attempt {attempt}: {str(exc)[:180]}")
                    if not _is_temporary_ai_error(exc):
                        break
    finally:
        try:
            client.close()
        except Exception:
            pass
    details = " | ".join(errors[-4:])
    raise HTTPException(502, f"မြန်မာ Recap ရေးရာမှာ Gemini မော်ဒယ်များ မရနိုင်သေးပါ: {details[:650]}")


@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "app": "SHEIN RECAP", "version": "0.3.0", "ffmpeg": Path(ffmpeg_path()).is_file(), "ai_ready": bool(os.getenv("GEMINI_API_KEY")), "ai_provider": "Google Gemini Free Tier", "tts": "Microsoft Edge Burmese voices"}

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
        run_cmd(["yt-dlp", "--no-playlist", "--ffmpeg-location", ffmpeg_path(), "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "-o", str(downloaded), youtube_url.strip()])
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

def group_word_boundaries(words):
    segments = []
    current = []
    start = 0.0
    end = 0.0
    for word in words:
        token = word["text"]
        if not current:
            start = word["start"]
        current.append(token)
        end = max(end, word["end"])
        joined = "".join(current).strip()
        if len(current) >= 6 or any(joined.endswith(mark) for mark in ("။", "?", "!", ",", "၊", ";", ":")):
            text = "".join(current).replace(" ၊", "၊").replace(" ။", "။")
            segments.append({"start": round(start, 3), "end": round(max(end, start + 0.35), 3), "text": text})
            current = []
    if current:
        text = "".join(current).replace(" ၊", "၊").replace(" ။", "။")
        segments.append({"start": round(start, 3), "end": round(max(end, start + 0.45), 3), "text": text})
    return segments


def get_audio_duration(audio: Path) -> float:
    # Read the actual encoded audio duration with FFmpeg (works for MP3 output).
    result = subprocess.run(
        [ffmpeg_path(), "-i", str(audio), "-f", "null", "-"],
        capture_output=True, text=True, timeout=60
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
    if not match:
        raise RuntimeError("အသံဖိုင်ကြာချိန်ကို မဖတ်နိုင်ပါ။")
    hours, minutes, seconds = match.groups()
    return max(0.1, int(hours) * 3600 + int(minutes) * 60 + float(seconds))


def estimate_subtitle_segments(script: str, duration: float):
    # Burmese Edge TTS voices may omit WordBoundary events. Split readable
    # caption chunks and distribute them across the real audio duration.
    clean = re.sub(r"\s+", " ", script[:12000]).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[။!?])\s*", clean) if s.strip()]
    chunks = []
    for sentence in sentences or ([clean] if clean else []):
        while len(sentence) > 52:
            cut = sentence.rfind(" ", 0, 52)
            if cut < 20:
                cut = 52
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    if not chunks:
        raise RuntimeError("Subtitle စာသား မရှိပါ။")
    weights = [max(1, len(re.sub(r"\s", "", chunk))) for chunk in chunks]
    total = sum(weights)
    segments = []
    cursor = 0.0
    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        finish = duration if index == len(chunks) - 1 else cursor + duration * weight / total
        segments.append({
            "start": round(cursor, 3),
            "end": round(max(cursor + 0.25, finish), 3),
            "text": chunk
        })
        cursor = finish
    return segments

@app.post("/api/speech")
async def create_speech(script: str = Form(...), voice: str = Form("my-MM-ThihaNeural"), speed: float = Form(1.0), tone: str = Form("သဘာဝကျပြီး ရှင်းလင်းသော အသံ")):
    if not script.strip():
        raise HTTPException(400, "အသံဖန်တီးရန် စာသားထည့်ပေးပါ။")
    voices = {"my-MM-ThihaNeural", "my-MM-NilarNeural"}
    if voice not in voices:
        raise HTTPException(400, "ရွေးထားတဲ့ မြန်မာအသံအမျိုးအစား မမှန်ပါ။")
    if not 0.7 <= speed <= 1.3:
        raise HTTPException(400, "အသံအမြန်နှုန်းကို 0.7 မှ 1.3 အတွင်းထားပါ။")
    speech_id = uuid4().hex
    output = OUTPUTS / f"{speech_id}.mp3"
    rate = f"{round((speed - 1) * 100):+d}%"
    words = []
    try:
        import edge_tts
        communicate = edge_tts.Communicate(script[:12000], voice, rate=rate)
        with output.open("wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    offset = chunk.get("offset", 0) / 10_000_000
                    duration = chunk.get("duration", 0) / 10_000_000
                    words.append({"start": max(0.0, offset), "end": max(0.0, offset + duration), "text": chunk.get("text", "")})
    except Exception as exc:
        output.unlink(missing_ok=True)
        raise HTTPException(502, f"အသံဖန်တီးရာမှာ အမှားဖြစ်နေပါတယ်: {str(exc)[:400]}")
    try:
        if words:
            segments = group_word_boundaries(words)
        else:
            duration = get_audio_duration(output)
            segments = estimate_subtitle_segments(script, duration)
    except Exception as exc:
        output.unlink(missing_ok=True)
        raise HTTPException(502, f"Subtitle အချိန်သတ်မှတ်ရာမှာ အမှားဖြစ်နေပါတယ်: {str(exc)[:400]}")
    (OUTPUTS / f"{speech_id}.json").write_text(__import__("json").dumps(segments, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "speech_id": speech_id, "audio_url": f"/api/file/{output.name}", "segments": segments}

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
async def export_video(file_id: str = Form(...), blur_x: int = Form(-1), blur_y: int = Form(-1), blur_w: int = Form(0), blur_h: int = Form(0), blur_start: float = Form(0), blur_end: float = Form(0), blur_strength: int = Form(20), audio_mode: str = Form("ai"), original_volume: int = Form(35), ai_volume: int = Form(100), subtitle_frames: list[UploadFile] = File(default=[]), subtitle_timings: str = Form("[]"), speech_id: str = Form("")):
    matches = list(UPLOADS.glob(file_id + ".*"))
    if not matches:
        raise HTTPException(404, "Video မတွေ့ပါ။")
    source = matches[0]
    output = OUTPUTS / f"{uuid4().hex}_vertical.mp4"
    base_filter = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
    # 720p vertical output reduces peak memory on Render Free (512 MB).
    frame_paths = []
    try:
        timings = json.loads(subtitle_timings or "[]")
    except Exception:
        raise HTTPException(400, "Subtitle timing data မမှန်ပါ။")
    if len(subtitle_frames) != len(timings):
        raise HTTPException(400, "Subtitle ပုံနဲ့ အချိန်အချက်အလက် မကိုက်ညီပါ။")
    if len(timings) > 300:
        raise HTTPException(400, "Subtitle အပိုင်း ၃၀၀ ထက် မကျော်ရပါ။")
    for frame in subtitle_frames:
        path = OUTPUTS / f"{uuid4().hex}_caption.png"
        with path.open("wb") as f:
            while chunk := await frame.read(1024 * 1024):
                f.write(chunk)
        frame_paths.append(path)
    blur_strength = max(1, min(40, blur_strength))
    blur_w = max(0, min(1080, blur_w))
    blur_h = max(0, min(1920, blur_h))
    blur_x = max(0, min(1080 - blur_w, blur_x)) if blur_w else blur_x
    blur_y = max(0, min(1920 - blur_h, blur_y)) if blur_h else blur_y
    has_blur = blur_x >= 0 and blur_y >= 0 and blur_w >= 2 and blur_h >= 2 and blur_end > blur_start
    # Blur editor coordinates remain based on the 1080x1920 preview; scale them to 720x1280.
    blur_x_out, blur_y_out = round(blur_x * 2 / 3), round(blur_y * 2 / 3)
    blur_w_out, blur_h_out = max(2, round(blur_w * 2 / 3)), max(2, round(blur_h * 2 / 3))
    audio_mode = audio_mode if audio_mode in ("ai", "original", "mix") else "ai"
    original_volume = max(0, min(100, original_volume)) / 100
    ai_volume = max(0, min(150, ai_volume)) / 100
    args = ["ffmpeg", "-y", "-i", str(source)]
    speech_path = OUTPUTS / f"{speech_id}.mp3" if speech_id and audio_mode in ("ai", "mix") else None
    if audio_mode in ("ai", "mix"):
        if not speech_path or not speech_path.is_file():
            raise HTTPException(404, "AI အသံဖိုင် မတွေ့ပါ။ အသံကို ပြန်ဖန်တီးပေးပါ။")
        args += ["-i", str(speech_path)]
    source_probe = subprocess.run([ffmpeg_path(), "-i", str(source)], capture_output=True, text=True, timeout=30)
    has_original_audio = "Audio:" in (source_probe.stderr or "")
    audio_filters = []
    if audio_mode == "original":
        if has_original_audio:
            audio_filters.append(f"[0:a]volume={original_volume:.2f}[aout]")
            audio_input = "[aout]"
        else:
            raise HTTPException(400, "မူရင်းဗီဒီယိုမှာ အသံလမ်းကြောင်း မတွေ့ပါ။ AI အသံ သို့မဟုတ် အသံနှစ်မျိုး ရွေးပါ။")
    elif audio_mode == "ai":
        audio_filters.append(f"[1:a]volume={ai_volume:.2f}[aout]")
        audio_input = "[aout]"
    else:
        if has_original_audio:
            audio_filters.extend([f"[0:a]volume={original_volume:.2f}[orig]", f"[1:a]volume={ai_volume:.2f}[voice]", "[orig][voice]amix=inputs=2:duration=longest:dropout_transition=2[aout]"])
        else:
            audio_filters.append(f"[1:a]volume={ai_volume:.2f}[aout]")
        audio_input = "[aout]"
    for path in frame_paths:
        args += ["-loop", "1", "-framerate", "30", "-i", str(path)]
    filters = list(audio_filters)
    if has_blur:
        filters.append(f"[0:v]{base_filter},split[base][tmp];[tmp]crop={blur_w_out}:{blur_h_out}:{blur_x_out}:{blur_y_out},boxblur={blur_strength}:2[blur];[base][blur]overlay={blur_x_out}:{blur_y_out}:enable='between(t,{blur_start},{blur_end})'[v0]")
        current = "v0"
    else:
        filters.append(f"[0:v]{base_filter}[v0]")
        current = "v0"
    for i, timing in enumerate(timings):
        try:
            begin = max(0.0, float(timing["start"]))
            finish = max(begin + 0.05, float(timing["end"]))
        except Exception:
            raise HTTPException(400, "Subtitle အချိန်တန်ဖိုး မမှန်ပါ။")
        next_label = f"v{i + 1}"
        input_index = (2 if speech_path else 1) + i
        filters.append(f"[{input_index}:v]scale=720:1280:flags=bicubic,format=rgba[cap{i}];[{current}][cap{i}]overlay=0:0:enable='between(t,{begin:.3f},{finish:.3f})'[{next_label}]")
        current = next_label
    args += ["-filter_complex_threads", "1", "-filter_complex", ";".join(filters), "-map", f"[{current}]", "-map", audio_input,
             "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", "-movflags", "+faststart", "-shortest", str(output)]
    try:
        run_cmd(args)
    finally:
        for path in frame_paths:
            path.unlink(missing_ok=True)
    return {"ok": True, "video_url": f"/api/file/{output.name}", "narration_audio_used": bool(speech_path)}
