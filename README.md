# SHEIN RECAP

A Burmese-first AI movie recap workspace with a mobile-friendly interface.

## Features planned
- YouTube URL input and local video upload
- Burmese recap script workspace
- Male/female voice selection, speed and tone controls
- Subtitle workflow
- Selectable-area video blur workflow
- AI scene-cut workflow
- 9:16 TikTok export workflow
- Thumbnail maker

## Run locally
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000.

## Environment
Set `OPENAI_API_KEY` in the deployment environment to enable AI-powered generation. Video processing and text-to-speech providers can be connected as the next implementation stage.

## Deployment
Create a Python web service using the repository root, build command `pip install -r requirements.txt`, and start command `uvicorn app:app --host 0.0.0.0 --port $PORT`.
