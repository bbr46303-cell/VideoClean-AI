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


# ==========================================
# APP
# ==========================================

APP = FastAPI(title="VideoClean AI API")


APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ==========================================
# DIRECTORIES
# ==========================================

ROOT = Path(__file__).resolve().parent

FRONTEND = ROOT / "index.html"

IN = ROOT / "uploads"
OUT = ROOT / "outputs"

IN.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)


# ==========================================
# RAZORPAY
# ==========================================

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")


if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    print("WARNING: Razorpay environment variables are missing.")


razorpay_client = None

if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:

    razorpay_client = razorpay.Client(
        auth=(
            RAZORPAY_KEY_ID,
            RAZORPAY_KEY_SECRET
        )
    )


# ==========================================
# HOME
# ==========================================

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


# ==========================================
# RAZORPAY CONFIG
# ==========================================

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


# ==========================================
# CREATE RAZORPAY ORDER
# ==========================================

@APP.post("/api/create-order")
async def create_order(data: dict):

    if not razorpay_client:

        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
        )


    try:

        amount = int(
            data.get(
                "amount",
                0
            )
        )

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


    currency = data.get(
        "currency",
        "INR"
    )


    receipt = data.get(
        "receipt",
        f"receipt_{uuid.uuid4().hex[:12]}"
    )


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


        if (
            "authentication" in error_text
            or
            "unauthorized" in error_text
        ):

            raise HTTPException(
                status_code=401,
                detail="Razorpay authentication failed"
            )


        raise HTTPException(
            status_code=500,
            detail="Unable to create Razorpay order"
        )


# ==========================================
# VERIFY PAYMENT
# ==========================================

@APP.post("/api/verify-payment")
async def verify_payment(data: dict):

    if not RAZORPAY_KEY_SECRET:

        raise HTTPException(
            status_code=500,
            detail="Razorpay secret is not configured"
        )


    payment_id = data.get(
        "razorpay_payment_id"
    )

    order_id = data.get(
        "razorpay_order_id"
    )

    signature = data.get(
        "razorpay_signature"
    )


    if not payment_id or not order_id or not signature:

        raise HTTPException(
            status_code=400,
            detail="Missing payment verification fields"
        )


    generated_signature = hmac.new(

        RAZORPAY_KEY_SECRET.encode(
            "utf-8"
        ),

        f"{order_id}|{payment_id}".encode(
            "utf-8"
        ),

        hashlib.sha256

    ).hexdigest()


    if not hmac.compare_digest(
        generated_signature,
        signature
    ):

        raise HTTPException(
            status_code=400,
            detail="Payment signature verification failed"
        )


    return {

        "success": True,

        "message":
            "Payment verified successfully",

        "razorpay_payment_id":
            payment_id,

        "razorpay_order_id":
            order_id

    }


# ==========================================
# PROCESS VIDEO
# ==========================================

@APP.post("/process-video")
async def process_video(

    video: UploadFile = File(...),

    x: int = Form(0),

    y: int = Form(0),

    w: int = Form(0),

    h: int = Form(0),

    enhance: bool = Form(True),

    audio_clean: bool = Form(True)

):

    # --------------------------------------
    # CREATE JOB
    # --------------------------------------

    job = uuid.uuid4().hex


    # --------------------------------------
    # FILE PATHS
    # --------------------------------------

    filename = Path(
        video.filename or "video.mp4"
    ).name


    src = IN / f"{job}_{filename}"

    dst = OUT / f"{job}.mp4"


    # --------------------------------------
    # SAVE UPLOADED VIDEO
    # --------------------------------------

    try:

        src.write_bytes(
            await video.read()
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail="Unable to save uploaded video"
        )


    # --------------------------------------
    # VIDEO FILTERS
    # --------------------------------------

    vf = []


    if enhance:

        vf.append(
            "hqdn3d=1.2:1.2:6:6,"
            "eq=contrast=1.04:saturation=1.05"
        )


    if w > 0 and h > 0:

        vf.append(

            f"delogo="
            f"x={x}:"
            f"y={y}:"
            f"w={w}:"
            f"h={h}:"
            f"show=0"

        )


    # --------------------------------------
    # FFMPEG COMMAND
    # --------------------------------------

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


    # --------------------------------------
    # AUDIO CLEANUP
    # --------------------------------------

    if audio_clean:

        cmd += [

            "-af",

            "highpass=f=80,"
            "lowpass=f=16000,"
            "afftdn"

        ]


    # --------------------------------------
    # OUTPUT SETTINGS
    # --------------------------------------

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


    # --------------------------------------
    # RUN FFMPEG
    # --------------------------------------

    try:

        result = subprocess.run(

            cmd,

            check=True,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE

        )


    except subprocess.CalledProcessError as e:

        error_details = (
            e.stderr
            .decode(
                errors="ignore"
            )
            [-2000:]
        )


        return {

            "error":
                "FFmpeg processing failed",

            "details":
                error_details

        }


    # --------------------------------------
    # CHECK OUTPUT
    # --------------------------------------

    if not dst.exists():

        raise HTTPException(

            status_code=500,

            detail=
                "Processed video file was not created"

        )


    # --------------------------------------
    # SUCCESS
    # --------------------------------------

    return {

        "success": True,

        "job": job,

        "download":
            f"/download/{job}"

    }


# ==========================================
# DOWNLOAD PROCESSED VIDEO
# ==========================================

@APP.get("/download/{job}")
def download(job: str):

    # Security:
    # Only allow the generated UUID job name.

    if not job.isalnum():

        raise HTTPException(

            status_code=400,

            detail="Invalid job ID"

        )


    p = OUT / f"{job}.mp4"


    # --------------------------------------
    # FILE NOT FOUND
    # --------------------------------------

    if not p.exists():

        raise HTTPException(

            status_code=404,

            detail="Processed video not found"

        )


    # --------------------------------------
    # DOWNLOAD FILE
    # --------------------------------------

    return FileResponse(

        path=str(p),

        media_type="video/mp4",

        filename=
            "VideoClean_AI_output.mp4"

    )


# ==========================================
# HEALTH CHECK
# ==========================================

@APP.get("/health")
def health():

    return {

        "status": "ok",

        "service": "VideoClean AI"

        }
