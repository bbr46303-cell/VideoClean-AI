from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import subprocess
import uuid
import os
import hmac
import hashlib
import sqlite3
import razorpay

APP = FastAPI(title="VideoClean AI API")

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "index.html"
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "outputs"
DB_FILE = ROOT / "usage.db"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_PLAN_ID = os.getenv("RAZORPAY_PLAN_ID")

razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    )
else:
    print("WARNING: Razorpay keys are not configured.")

MAX_VIDEOS_PER_MONTH = 50
MAX_VIDEO_SECONDS = 10 * 60


def db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            subscription_id TEXT NOT NULL,
            cycle_start INTEGER NOT NULL,
            videos_used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(subscription_id, cycle_start)
        )
    """)
    con.commit()
    return con


def get_subscription(subscription_id: str):
    if not razorpay_client:
        raise HTTPException(status_code=500, detail="Razorpay is not configured")
    if not subscription_id or not subscription_id.startswith("sub_"):
        raise HTTPException(status_code=400, detail="Invalid subscription")
    try:
        return razorpay_client.subscription.fetch(subscription_id)
    except Exception as e:
        print("Subscription fetch error:", str(e))
        raise HTTPException(status_code=400, detail="Unable to verify subscription")


def check_active_subscription(subscription_id: str):
    sub = get_subscription(subscription_id)
    status = str(sub.get("status", "")).lower()
    allowed = {"active", "authenticated"}
    if status not in allowed:
        raise HTTPException(
            status_code=402,
            detail=f"Subscription is not active ({status})"
        )
    return sub


def reserve_video_slot(subscription_id: str, cycle_start: int):
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT videos_used FROM usage WHERE subscription_id=? AND cycle_start=?",
            (subscription_id, cycle_start)
        ).fetchone()
        used = row[0] if row else 0
        if used >= MAX_VIDEOS_PER_MONTH:
            con.rollback()
            raise HTTPException(
                status_code=429,
                detail="Monthly limit reached: 50 videos per billing cycle."
            )
        if row:
            con.execute(
                "UPDATE usage SET videos_used=videos_used+1 "
                "WHERE subscription_id=? AND cycle_start=?",
                (subscription_id, cycle_start)
            )
        else:
            con.execute(
                "INSERT INTO usage(subscription_id, cycle_start, videos_used) VALUES(?,?,1)",
                (subscription_id, cycle_start)
            )
        con.commit()
    finally:
        con.close()


@APP.get("/")
def home():
    if FRONTEND.exists():
        return FileResponse(str(FRONTEND), media_type="text/html")
    return {"status": "ok", "message": "VideoClean AI backend is running"}


@APP.get("/health")
def health():
    return {"status": "ok", "service": "VideoClean AI"}


@APP.get("/api/razorpay-config")
def razorpay_config():
    if not RAZORPAY_KEY_ID:
        raise HTTPException(status_code=500, detail="Razorpay Key ID is not configured")
    if not RAZORPAY_PLAN_ID:
        raise HTTPException(status_code=500, detail="RAZORPAY_PLAN_ID is not configured")
    return {
        "key_id": RAZORPAY_KEY_ID,
        "plan_id": RAZORPAY_PLAN_ID,
        "price": 99,
        "currency": "INR",
        "videos_per_month": MAX_VIDEOS_PER_MONTH,
        "max_minutes": 10
    }


@APP.post("/api/create-subscription")
async def create_subscription(data: dict):
    if razorpay_client is None:
        raise HTTPException(status_code=500, detail="Razorpay is not configured")
    if not RAZORPAY_PLAN_ID:
        raise HTTPException(status_code=500, detail="RAZORPAY_PLAN_ID is not configured")

    try:
        sub = razorpay_client.subscription.create({
            "plan_id": RAZORPAY_PLAN_ID,
            "total_count": 1200,
            "quantity": 1,
            "customer_notify": True
        })
        return {
            "subscription_id": sub["id"],
            "status": sub.get("status", "created")
        }
    except Exception as e:
        text = str(e)
        print("Razorpay subscription error:", text)
        if "authentication" in text.lower() or "unauthorized" in text.lower():
            raise HTTPException(status_code=401, detail="Razorpay authentication failed")
        raise HTTPException(status_code=500, detail="Unable to create subscription")


@APP.post("/api/verify-subscription")
async def verify_subscription(data: dict):
    if not RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=500, detail="Razorpay secret is not configured")

    payment_id = data.get("razorpay_payment_id")
    subscription_id = data.get("razorpay_subscription_id")
    signature = data.get("razorpay_signature")

    if not payment_id or not subscription_id or not signature:
        raise HTTPException(status_code=400, detail="Missing subscription verification fields")

    generated = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{payment_id}|{subscription_id}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(generated, signature):
        raise HTTPException(status_code=400, detail="Subscription signature verification failed")

    sub = check_active_subscription(subscription_id)
    return {
        "success": True,
        "subscription_id": subscription_id,
        "status": sub.get("status"),
        "message": "Subscription verified successfully"
    }


@APP.get("/api/subscription-status")
def subscription_status(subscription_id: str):
    sub = check_active_subscription(subscription_id)
    cycle_start = int(sub.get("current_start") or sub.get("start_at") or 0)

    con = db()
    row = con.execute(
        "SELECT videos_used FROM usage WHERE subscription_id=? AND cycle_start=?",
        (subscription_id, cycle_start)
    ).fetchone()
    con.close()

    used = row[0] if row else 0
    return {
        "active": True,
        "status": sub.get("status"),
        "videos_used": used,
        "videos_remaining": max(0, MAX_VIDEOS_PER_MONTH - used),
        "max_minutes": 10
    }


@APP.post("/process-video")
async def process_video(
    video: UploadFile = File(...),
    subscription_id: str = Form(...),
    enhance: bool = Form(True),
    audio_clean: bool = Form(True)
):
    print("PROCESS VIDEO REQUEST RECEIVED")

    sub = check_active_subscription(subscription_id)
    cycle_start = int(sub.get("current_start") or sub.get("start_at") or 0)
    if not cycle_start:
        raise HTTPException(status_code=402, detail="Billing cycle is not available yet")

    # Reserve one monthly slot before processing.
    reserve_video_slot(subscription_id, cycle_start)

    job = uuid.uuid4().hex
    original_name = Path(video.filename or "video.mp4").name
    input_file = UPLOAD_DIR / f"{job}_{original_name}"
    output_file = OUTPUT_DIR / f"{job}.mp4"

    try:
        video_data = await video.read()
        if not video_data:
            raise HTTPException(status_code=400, detail="Uploaded video is empty")
        input_file.write_bytes(video_data)
    except HTTPException:
        raise
    except Exception as e:
        print("Upload error:", str(e))
        raise HTTPException(status_code=500, detail="Unable to save uploaded video")

    # Check duration with ffprobe. Maximum: 10 minutes.
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_file)
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        duration = float(probe.stdout.strip())
    except Exception as e:
        input_file.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Could not read video duration")

    if duration > MAX_VIDEO_SECONDS:
        input_file.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="Maximum video length is 10 minutes."
        )

    video_filters = []
    if enhance:
        video_filters.append("eq=contrast=1.03:saturation=1.03")

    command = ["ffmpeg", "-y", "-i", str(input_file)]

    if video_filters:
        command += ["-vf", ",".join(video_filters)]

    if audio_clean:
        command += ["-af", "highpass=f=80,lowpass=f=16000"]

    command += [
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_file)
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except FileNotFoundError:
        input_file.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="FFmpeg is not installed on server.")
    except subprocess.CalledProcessError as e:
        input_file.unlink(missing_ok=True)
        error_text = e.stderr.decode(errors="ignore")
        print("FFmpeg ERROR:", error_text[-2000:])
        raise HTTPException(status_code=500, detail="Video processing failed")

    input_file.unlink(missing_ok=True)

    if not output_file.exists():
        raise HTTPException(status_code=500, detail="Processed video was not created")

    return {
        "success": True,
        "job": job,
        "download": f"/download/{job}"
    }


@APP.get("/download/{job}")
def download(job: str):
    if not job.isalnum():
        raise HTTPException(status_code=400, detail="Invalid job ID")

    output_file = OUTPUT_DIR / f"{job}.mp4"
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Processed video not found")

    return FileResponse(
        path=str(output_file),
        media_type="video/mp4",
        filename="VideoClean_AI_output.mp4"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        APP,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000"))
    )
    
