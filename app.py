from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import subprocess
import uuid
import os
import hmac
import hashlib
import razorpay

APP = FastAPI(title="VideoClean AI API")

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "index.html"
IN = ROOT / "uploads"
OUT = ROOT / "outputs"

IN.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

# Razorpay credentials are read ONLY from environment variables.
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    print("WARNING: Razorpay environment variables are missing.")

razorpay_client = razorpay.Client(
    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
)


@APP.get("/")
def home():
    if FRONTEND.exists():
        return FileResponse(FRONTEND, media_type="text/html")

    return {
        "status": "ok",
        "message": "VideoClean AI backend is running"
    }


# Public Razorpay Key ID for frontend.
# Secret key is NEVER returned.
@APP.get("/api/razorpay-config")
def razorpay_config():
    if not RAZORPAY_KEY_ID:
        raise HTTPException(
            status_code=500,
            detail="Razorpay Key ID is not configured"
        )

    return {
        "key_id": RAZORPAY_KEY_ID
    }


# Create Razorpay order
@APP.post("/api/create-order")
async def create_order(data: dict):
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Invalid amount"
        )

    if amount < 100:
        raise HTTPException(
            status_code=400,
            detail="Minimum payment amount is 100 paise"
        )

    currency = data.get("currency", "INR")
    receipt = data.get("receipt", f"receipt_{uuid.uuid4().hex[:12]}")

    try:
        order = razorpay_client.order.create({
            "amount": amount,
            "currency": currency,
            "receipt": receipt
        })

        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"]
        }

    except Exception as e:
        error_text = str(e).lower()

        if "authentication" in error_text or "unauthorized" in error_text:
            raise HTTPException(
                status_code=401,
                detail="Razorpay authentication failed"
            )

        raise HTTPException(
            status_code=500,
            detail="Unable to create Razorpay order"
        )


# Verify Razorpay payment signature
@APP.post("/api/verify-payment")
async def verify_payment(data: dict):

    payment_id = data.get("razorpay_payment_id")
    order_id = data.get("razorpay_order_id")
    signature = data.get("razorpay_signature")

    if not payment_id or not order_id or not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing payment verification fields"
        )

    generated_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, signature):
        raise HTTPException(
            status_code=400,
            detail="Payment signature verification failed"
        )

    return {
        "success": True,
        "message": "Payment verified successfully",
        "razorpay_payment_id": payment_id,
        "razorpay_order_id": order_id
    }


@APP.post("/process")
async def process_video(
    video: UploadFile = File(...),
    x: int = Form(0),
    y: int = Form(0),
    w: int = Form(0),
    h: int = Form(0),
    enhance: bool = Form(True),
    audio_clean: bool = Form(True)
):
    job = uuid.uuid4().hex
    src = IN / f"{job}_{video.filename}"
    dst = OUT / f"{job}.mp4"

    src.write_bytes(await video.read())

    vf = []

    if enhance:
        vf.append(
            "hqdn3d=1.2:1.2:6:6,eq=contrast=1.04:saturation=1.05"
        )

    if w > 0 and h > 0:
        vf.append(
            f"delogo=x={x}:y={y}:w={w}:h={h}:show=0"
        )

    cmd = ["ffmpeg", "-y", "-i", str(src)]

    if vf:
        cmd += ["-vf", ",".join(vf)]

    if audio_clean:
        cmd += [
            "-af",
            "highpass=f=80,lowpass=f=16000,afftdn"
        ]

    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(dst)
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

    except subprocess.CalledProcessError as e:
        return {
            "error": "FFmpeg processing failed",
            "details": e.stderr.decode(errors="ignore")[-1500:]
        }

    return {
        "job": job,
        "download": f"/download/{job}"
    }


@APP.get("/download/{job}")
def download(job: str):
    p = OUT / f"{job}.mp4"

    if not p.exists():
        return {"error": "File not found"}

    return FileResponse(
        p,
        media_type="video/mp4",
        filename="VideoClean_AI_output.mp4"
    )
