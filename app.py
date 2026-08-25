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


# =========================
# APP
# =========================

APP = FastAPI(title="VideoClean AI API")

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================
# PATHS
# =========================

ROOT = Path(__file__).resolve().parent

FRONTEND = ROOT / "index.html"
IN = ROOT / "uploads"
OUT = ROOT / "outputs"

IN.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)


# =========================
# RAZORPAY CONFIG
# =========================

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

razorpay_client = None

if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    )


# =========================
# HOME
# =========================

@APP.get("/")
def home():

    if FRONTEND.exists():
        return FileResponse(
            FRONTEND,
            media_type="text/html"
        )

    return {
        "status": "ok",
        "message": "VideoClean AI backend is running"
    }


# =========================
# VIDEO PROCESSING
# =========================

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
            "hqdn3d=1.2:1.2:6:6,"
            "eq=contrast=1.04:saturation=1.05"
        )

    if w > 0 and h > 0:
        vf.append(
            f"delogo=x={x}:y={y}:w={w}:h={h}:show=0"
        )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src)
    ]

    if vf:
        cmd += [
            "-vf",
            ",".join(vf)
        ]

    if audio_clean:
        cmd += [
            "-af",
            "highpass=f=80,lowpass=f=16000,afftdn"
        ]

    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
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
            "details": e.stderr.decode(
                errors="ignore"
            )[-1500:]
        }

    return {
        "job": job,
        "download": f"/download/{job}"
    }


# =========================
# DOWNLOAD
# =========================

@APP.get("/download/{job}")
def download(job: str):

    p = OUT / f"{job}.mp4"

    if not p.exists():
        return {
            "error": "File not found"
        }

    return FileResponse(
        p,
        media_type="video/mp4",
        filename="VideoClean_AI_output.mp4"
    )


# =========================
# RAZORPAY CREATE ORDER
# =========================

@APP.post("/api/create-order")
async def create_order():

    if not razorpay_client:
        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured on the server."
        )

    # Creator plan = ₹99
    # Razorpay amount is in paise.
    amount = 9900

    if amount < 100:
        raise HTTPException(
            status_code=400,
            detail="Minimum payment amount is 100 paise."
        )

    receipt = "vc_" + uuid.uuid4().hex[:16]

    try:

        order = razorpay_client.order.create(
            data={
                "amount": amount,
                "currency": "INR",
                "receipt": receipt,
                "notes": {
                    "plan": "creator",
                    "product": "VideoClean AI"
                }
            }
        )

        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": RAZORPAY_KEY_ID
        }

    except Exception as e:

        error_text = str(e)

        if (
            "401" in error_text
            or "authentication" in error_text.lower()
            or "unauthorized" in error_text.lower()
        ):
            raise HTTPException(
                status_code=401,
                detail="Razorpay authentication failed."
            )

        raise HTTPException(
            status_code=500,
            detail="Unable to create Razorpay order."
        )


# =========================
# RAZORPAY VERIFY PAYMENT
# =========================

@APP.post("/api/verify-payment")
async def verify_payment(data: dict):

    payment_id = data.get(
        "razorpay_payment_id"
    )

    order_id = data.get(
        "razorpay_order_id"
    )

    received_signature = data.get(
        "razorpay_signature"
    )

    if (
        not payment_id
        or not order_id
        or not received_signature
    ):
        raise HTTPException(
            status_code=400,
            detail="Missing payment verification fields."
        )

    if not RAZORPAY_KEY_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Razorpay secret is not configured."
        )

    # Razorpay signature:
    # HMAC-SHA256(order_id + "|" + payment_id)

    message = f"{order_id}|{payment_id}"

    generated_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(
        generated_signature,
        received_signature
    ):
        raise HTTPException(
            status_code=400,
            detail="Payment signature verification failed."
        )

    return {
        "success": True,
        "message": "Payment verified successfully.",
        "payment_id": payment_id,
        "order_id": order_id
    }
