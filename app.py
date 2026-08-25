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


# ==================================================
# VIDEO CLEAN AI
# BACKEND
# ==================================================

APP = FastAPI(
    title="VideoClean AI API"
)


# ==================================================
# CORS
# ==================================================

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ==================================================
# PATHS
# ==================================================

ROOT = Path(__file__).resolve().parent

FRONTEND = ROOT / "index.html"

UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "outputs"

UPLOAD_DIR.mkdir(
    exist_ok=True
)

OUTPUT_DIR.mkdir(
    exist_ok=True
)


# ==================================================
# RAZORPAY SETTINGS
# ==================================================

RAZORPAY_KEY_ID = os.getenv(
    "RAZORPAY_KEY_ID"
)

RAZORPAY_KEY_SECRET = os.getenv(
    "RAZORPAY_KEY_SECRET"
)


razorpay_client = None


if (
    RAZORPAY_KEY_ID
    and
    RAZORPAY_KEY_SECRET
):

    razorpay_client = razorpay.Client(
        auth=(
            RAZORPAY_KEY_ID,
            RAZORPAY_KEY_SECRET
        )
    )

else:

    print(
        "WARNING: Razorpay keys are not configured."
    )


# ==================================================
# HOME
# ==================================================

@APP.get("/")
def home():

    if FRONTEND.exists():

        return FileResponse(
            str(FRONTEND),
            media_type="text/html"
        )

    return {
        "status": "ok",
        "message": "VideoClean AI backend is running"
    }


# ==================================================
# HEALTH CHECK
# ==================================================

@APP.get("/health")
def health():

    return {
        "status": "ok",
        "service": "VideoClean AI"
    }


# ==================================================
# RAZORPAY CONFIG
# ==================================================

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


# ==================================================
# CREATE RAZORPAY ORDER
# ==================================================

@APP.post("/api/create-order")
async def create_order(data: dict):

    if razorpay_client is None:

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
        "receipt_" + uuid.uuid4().hex[:12]
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


        print(
            "Razorpay error:",
            str(e)
        )


        raise HTTPException(
            status_code=500,
            detail="Unable to create Razorpay order"
        )


# ==================================================
# VERIFY RAZORPAY PAYMENT
# ==================================================

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


    if (
        not payment_id
        or
        not order_id
        or
        not signature
    ):

        raise HTTPException(
            status_code=400,
            detail="Missing payment verification fields"
        )


    generated_signature = hmac.new(

        RAZORPAY_KEY_SECRET.encode(
            "utf-8"
        ),

        (
            f"{order_id}|{payment_id}"
        ).encode(
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


# ==================================================
# PROCESS VIDEO
# ==================================================

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

    print(
        "PROCESS VIDEO REQUEST RECEIVED"
    )


    # ------------------------------------------------
    # CREATE JOB ID
    # ------------------------------------------------

    job = uuid.uuid4().hex


    # ------------------------------------------------
    # SAFE FILE NAME
    # ------------------------------------------------

    original_name = Path(
        video.filename or "video.mp4"
    ).name


    # ------------------------------------------------
    # FILE PATHS
    # ------------------------------------------------

    input_file = (
        UPLOAD_DIR
        /
        f"{job}_{original_name}"
    )


    output_file = (
        OUTPUT_DIR
        /
        f"{job}.mp4"
    )


    # ------------------------------------------------
    # SAVE UPLOADED VIDEO
    # ------------------------------------------------

    try:

        video_data = await video.read()

        if not video_data:

            raise HTTPException(
                status_code=400,
                detail="Uploaded video is empty"
            )


        input_file.write_bytes(
            video_data
        )


        print(
            "Video uploaded:",
            input_file.name
        )


    except HTTPException:

        raise


    except Exception as e:

        print(
            "Upload error:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to save uploaded video"
        )


    # ------------------------------------------------
    # VIDEO FILTERS
    # ------------------------------------------------

    video_filters = []


    # FAST ENHANCEMENT
    if enhance:

        video_filters.append(
            "eq=contrast=1.03:saturation=1.03"
        )


    # OPTIONAL LOGO REMOVAL
    if (
        w > 0
        and
        h > 0
    ):

        video_filters.append(

            f"delogo="
            f"x={x}:"
            f"y={y}:"
            f"w={w}:"
            f"h={h}:"
            f"show=0"

        )


    # ------------------------------------------------
    # FFMPEG COMMAND
    # ------------------------------------------------

    command = [

        "ffmpeg",

        "-y",

        "-i",
        str(input_file)

    ]


    # Add video filters

    if video_filters:

        command += [

            "-vf",

            ",".join(
                video_filters
            )

        ]


    # ------------------------------------------------
    # AUDIO CLEANUP
    # ------------------------------------------------

    if audio_clean:

        command += [

            "-af",

            "highpass=f=80,"
            "lowpass=f=16000"

        ]


    # ------------------------------------------------
    # FAST ENCODING
    # ------------------------------------------------

    command += [

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-crf",
        "26",

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-movflags",
        "+faststart",

        str(output_file)

    ]


    print(
        "Starting FFmpeg..."
    )


    # ------------------------------------------------
    # RUN FFMPEG
    # ------------------------------------------------

    try:

        result = subprocess.run(

            command,

            check=True,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE

        )


        print(
            "FFmpeg completed."
        )


    except FileNotFoundError:

        print(
            "FFmpeg is not installed."
        )


        return {

            "error":
                "FFmpeg is not installed on server."

        }


    except subprocess.CalledProcessError as e:

        error_text = (
            e.stderr
            .decode(
                errors="ignore"
            )
        )


        print(
            "FFmpeg ERROR:",
            error_text[-2000:]
        )


        return {

            "error":
                "FFmpeg processing failed",

            "details":
                error_text[-2000:]

        }


    # ------------------------------------------------
    # CHECK OUTPUT
    # ------------------------------------------------

    if not output_file.exists():

        raise HTTPException(

            status_code=500,

            detail=
                "Processed video was not created"

        )


    # ------------------------------------------------
    # DELETE ORIGINAL UPLOAD
    # ------------------------------------------------

    try:

        input_file.unlink(
            missing_ok=True
        )

    except Exception:

        pass


    # ------------------------------------------------
    # SUCCESS
    # ------------------------------------------------

    print(
        "VIDEO PROCESSING SUCCESS:",
        job
    )


    return {

        "success": True,

        "job": job,

        "download":
            f"/download/{job}"

    }


# ==================================================
# DOWNLOAD PROCESSED VIDEO
# ==================================================

@APP.get("/download/{job}")
def download(job: str):

    print(
        "DOWNLOAD REQUEST:",
        job
    )


    # ------------------------------------------------
    # CHECK JOB ID
    # ------------------------------------------------

    if not job.isalnum():

        raise HTTPException(

            status_code=400,

            detail="Invalid job ID"

        )


    # ------------------------------------------------
    # OUTPUT FILE
    # ------------------------------------------------

    output_file = (
        OUTPUT_DIR
        /
        f"{job}.mp4"
    )


    # ------------------------------------------------
    # CHECK FILE
    # ------------------------------------------------

    if not output_file.exists():

        print(
            "DOWNLOAD FILE NOT FOUND:",
            output_file
        )


        raise HTTPException(

            status_code=404,

            detail="Processed video not found"

        )


    # ------------------------------------------------
    # SEND FILE
    # ------------------------------------------------

    print(
        "SENDING VIDEO:",
        output_file.name
    )


    return FileResponse(

        path=str(
            output_file
        ),

        media_type="video/mp4",

        filename=
            "VideoClean_AI_output.mp4"

    )


# ==================================================
# RUN
# ==================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        APP,

        host="0.0.0.0",

        port=int(
            os.getenv(
                "PORT",
                "10000"
            )
        )

    )
