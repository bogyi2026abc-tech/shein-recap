# SHEIN RECAP

A Burmese-first AI movie recap workspace with a responsive mobile interface.

## Current features
- YouTube URL or local video upload (up to 500MB)
- Audio extraction and transcription
- Burmese recap script generation with editable text
- AI voice generation with voice, speed, and tone controls
- 9:16 vertical video export
- Timed rectangular blur during export
- Thumbnail frame capture

## Render deployment

Create a new **Web Service** from this repository.

- Runtime: Python
- Build command: `apt-get update && apt-get install -y ffmpeg && pip install -r requirements.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

Add this environment variable in Render:

- `OPENAI_API_KEY`: your OpenAI API key

Optional:
- `OPENAI_TEXT_MODEL`: defaults to `gpt-4o-mini`

After deployment, open `/api/health` to check AI and FFmpeg readiness.

## API endpoints
- `GET /` — workspace UI
- `GET /api/health` — service status
- `POST /api/upload` — upload a video
- `POST /api/recap` — transcribe and generate Burmese recap
- `POST /api/speech` — create narration audio
- `POST /api/thumbnail` — capture a thumbnail frame
- `POST /api/export` — export 9:16 video with optional timed blur

## Important notes
- AI generation requires a valid API key and incurs API usage costs.
- YouTube downloads depend on YouTube access and the source video's availability; private, age-restricted, or blocked videos may fail.
- The selected AI voices are provider voice presets; male/female labels are approximate and the actual sound can vary.
- The blur rectangle uses coordinates on the final 1080x1920 output frame.
- This first working version does not yet include automatic subtitle timing, full AI scene editing, or a finished commercial billing/account system.
- Uploaded files and generated outputs are stored on the service filesystem. On a free Render instance, local files may be temporary and can be lost on restart/redeploy. Do not treat this as permanent storage.

## Local run
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```
