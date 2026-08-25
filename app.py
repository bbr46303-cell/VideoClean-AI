from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import subprocess, uuid, os

APP = FastAPI(title="VideoClean AI API")
APP.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "index.html"
IN = ROOT / "uploads"
OUT = ROOT / "outputs"
IN.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)

@APP.get("/")
def home():
    if FRONTEND.exists():
        return FileResponse(FRONTEND, media_type="text/html")
    return {"status":"ok","message":"VideoClean AI backend is running"}

@APP.post("/process")
async def process_video(
    video: UploadFile = File(...),
    x: int = Form(0), y: int = Form(0), w: int = Form(0), h: int = Form(0),
    enhance: bool = Form(True), audio_clean: bool = Form(True)
):
    job = uuid.uuid4().hex
    src = IN / f"{job}_{video.filename}"
    dst = OUT / f"{job}.mp4"
    src.write_bytes(await video.read())

    # This first backend uses FFmpeg for enhancement/audio cleanup.
    # Object/logo removal is activated when a rectangle is supplied.
    vf = []
    if enhance:
        vf.append("hqdn3d=1.2:1.2:6:6,eq=contrast=1.04:saturation=1.05")
    if w > 0 and h > 0:
        # FFmpeg delogo is practical for a fixed logo/watermark rectangle.
        vf.append(f"delogo=x={x}:y={y}:w={w}:h={h}:show=0")

    cmd = ["ffmpeg","-y","-i",str(src)]
    if vf:
        cmd += ["-vf",",".join(vf)]
    if audio_clean:
        cmd += ["-af","highpass=f=80,lowpass=f=16000,afftdn"]
    cmd += ["-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(dst)]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        return {"error":"FFmpeg processing failed","details":e.stderr.decode(errors="ignore")[-1500:]}

    return {"job":job,"download":f"/download/{job}"}

@APP.get("/download/{job}")
def download(job: str):
    p = OUT / f"{job}.mp4"
    if not p.exists():
        return {"error":"File not found"}
    return FileResponse(p, media_type="video/mp4", filename="VideoClean_AI_output.mp4")
