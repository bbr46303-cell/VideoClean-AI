from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import subprocess
import uuid
import os
import hmac
import hashlib
import json
import threading
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

USAGE_FILE = ROOT / "usage.json"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# ==================================================
# RAZORPAY SETTINGS
# ==================================================

RAZORPAY_KEY_ID = os.getenv(
    "RAZORPAY_KEY_ID"
)

RAZORPAY_KEY_SECRET = os.getenv(
    "RAZORPAY_KEY_SECRET"
)

RAZORPAY_PLAN_ID = os.getenv(
    "RAZORPAY_PLAN_ID",
    "plan_TU4y2sFEE55IWF"
)


razorpay_client = None


if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:

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
# USAGE STORAGE
# ==================================================

usage_lock = threading.Lock()


def load_usage():

    if not USAGE_FILE.exists():
        return {}

    try:

        return json.loads(
            USAGE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return {}


def save_usage(data):

    USAGE_FILE.write_text(
        json.dumps(
            data,
            indent=2
        ),
        encoding="utf-8"
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
# HEALTH
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
        "key_id": RAZORPAY_KEY_ID,
        "plan_id": RAZORPAY_PLAN_ID
    }


# ==================================================
# CREATE SUBSCRIPTION
# ==================================================

@APP.post("/api/create-subscription")
async def create_subscription():

    if razorpay_client is None:

        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
        )

    try:

        subscription = (
            razorpay_client.subscription.create({

                "plan_id": RAZORPAY_PLAN_ID,

                # 12 monthly billing cycles
                "total_count": 12,

                "quantity": 1,

                "customer_notify": True

            })
        )

        return {

            "success": True,

            "subscription_id":
                subscription["id"],

            "plan_id":
                RAZORPAY_PLAN_ID

        }

    except Exception as e:

        print(
            "Subscription error:",
            str(e)
        )

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
            detail="Unable to create subscription"
        )


# ==================================================
# VERIFY SUBSCRIPTION PAYMENT
# ==================================================

@APP.post("/api/verify-subscription")
async def verify_subscription(data: dict):

    if not RAZORPAY_KEY_SECRET:

        raise HTTPException(
            status_code=500,
            detail="Razorpay secret is not configured"
        )


    payment_id = data.get(
        "razorpay_payment_id"
    )

    subscription_id = data.get(
        "razorpay_subscription_id"
    )

    signature = data.get(
        "razorpay_signature"
    )


    if (
        not payment_id
        or
        not subscription_id
        or
        not signature
    ):

        raise HTTPException(
            status_code=400,
            detail="Missing subscription verification fields"
        )


    generated_signature = hmac.new(

        RAZORPAY_KEY_SECRET.encode(
            "utf-8"
        ),

        (
            f"{payment_id}|{subscription_id}"
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
            detail="Subscription payment verification failed"
        )


    # Confirm subscription exists
    try:

        subscription = (
            razorpay_client.subscription.fetch(
                subscription_id
            )
        )

        status = subscription.get(
            "status"
        )

        if status not in [
            "active",
            "authenticated"
        ]:

            raise HTTPException(
                status_code=400,
                detail="Subscription is not active"
            )

    except HTTPException:

        raise

    except Exception as e:

        print(
            "Subscription fetch error:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to verify subscription status"
        )


    return {

        "success": True,

        "message":
            "Subscription verified successfully",

        "subscription_id":
            subscription_id,

        "payment_id":
            payment_id,

        "status":
            status

    }


# ==================================================
# SUBSCRIPTION STATUS
# ==================================================

@APP.get("/api/subscription/{subscription_id}")
def subscription_status(
    subscription_id: str
):

    if razorpay_client is None:

        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
        )


    try:

        subscription = (
            razorpay_client.subscription.fetch(
                subscription_id
            )
        )

    except Exception:

        raise HTTPException(
            status_code=404,
            detail="Subscription not found"
        )


    status = subscription.get(
        "status"
    )


    current_start = subscription.get(
        "current_start"
    )

    current_end = subscription.get(
        "current_end"
    )


    # Current monthly cycle
    cycle_key = str(
        current_start or "default"
    )


    usage_key = (
        f"{subscription_id}_{cycle_key}"
    )


    with usage_lock:

        usage = load_usage()

        videos_used = int(
            usage.get(
                usage_key,
                0
            )
        )


    remaining = max(
        0,
        50 - videos_used
    )


    return {

        "subscription_id":
            subscription_id,

        "status":
            status,

        "videos_used":
            videos_used,

        "videos_remaining":
            remaining,

        "monthly_limit":
            50,

        "max_minutes":
            10,

        "current_start":
            current_start,

        "current_end":
            current_end

    }


# ==================================================
# GET VIDEO DURATION
# ==================================================

def get_video_duration(
    file_path: Path
):

    command = [

        "ffprobe",

        "-v",
        "error",

        "-show_entries",
        "format=duration",

        "-of",
        "default=noprint_wrappers=1:nokey=1",

        str(file_path)

    ]


    try:

        result = subprocess.run(

            command,

            check=True,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            text=True

        )

        return float(
            result.stdout.strip()
        )

    except Exception as e:

        print(
            "Duration error:",
            str(e)
        )

        return None


# ==================================================
# PROCESS VIDEO
# ==================================================

@APP.post("/process-video")
async def process_video(

    video: UploadFile = File(...),

    subscription_id: str = Form(...),

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


    # ==================================================
    # CHECK SUBSCRIPTION
    # ==================================================

    if razorpay_client is None:

        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
        )


    try:

        subscription = (
            razorpay_client.subscription.fetch(
                subscription_id
            )
        )

    except Exception:

        raise HTTPException(
            status_code=403,
            detail="Invalid subscription"
        )


    subscription_status_value = (
        subscription.get("status")
    )


    if subscription_status_value != "active":

        raise HTTPException(
            status_code=403,
            detail="Your monthly subscription is not active"
        )


    # ==================================================
    # CURRENT BILLING CYCLE
    # ==================================================

    current_start = subscription.get(
        "current_start"
    )


    cycle_key = str(
        current_start or "default"
    )


    usage_key = (
        f"{subscription_id}_{cycle_key}"
    )


    # ==================================================
    # CHECK 50 VIDEO LIMIT
    # ==================================================

    with usage_lock:

        usage = load_usage()

        videos_used = int(
            usage.get(
                usage_key,
                0
            )
        )


        if videos_used >= 50:

            raise HTTPException(
                status_code=403,
                detail=
                    "Monthly limit reached. "
                    "You can process up to 50 videos per month."
            )


    # ==================================================
    # CREATE JOB
    # ==================================================

    job = uuid.uuid4().hex


    original_name = Path(
        video.filename or "video.mp4"
    ).name


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


    # ==================================================
    # SAVE VIDEO
    # ==================================================

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


    # ==================================================
    # CHECK VIDEO DURATION
    # ==================================================

    duration = get_video_duration(
        input_file
    )


    if duration is None:

        input_file.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=400,
            detail="Unable to read video duration"
        )


    if duration > 600:

        input_file.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=400,
            detail=
                "Maximum video length is 10 minutes."
        )


    # ==================================================
    # VIDEO FILTERS
    # ==================================================

    video_filters = []


    if enhance:

        video_filters.append(
            "eq=contrast=1.03:saturation=1.03"
        )


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


    # ==================================================
    # FFMPEG
    # ==================================================

    command = [

        "ffmpeg",

        "-y",

        "-i",
        str(input_file)

    ]


    if video_filters:

        command += [

            "-vf",

            ",".join(
                video_filters
            )

        ]


    if audio_clean:

        command += [

            "-af",

            "highpass=f=80,"
            "lowpass=f=16000"

        ]


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


    # ==================================================
    # RUN FFMPEG
    # ==================================================

    try:

        subprocess.run(

            command,

            check=True,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE

        )

    except FileNotFoundError:

        input_file.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=500,
            detail="FFmpeg is not installed on server"
        )


    except subprocess.CalledProcessError as e:

        input_file.unlink(
            missing_ok=True
        )

        error_text = (
            e.stderr.decode(
                errors="ignore"
            )
        )


        print(
            "FFmpeg ERROR:",
            error_text[-2000:]
        )


        raise HTTPException(
            status_code=500,
            detail="Video processing failed"
        )


    # ==================================================
    # CHECK OUTPUT
    # ==================================================

    if not output_file.exists():

        input_file.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=500,
            detail="Processed video was not created"
        )


    # ==================================================
    # COUNT VIDEO
    # ==================================================

    with usage_lock:

        usage = load_usage()

        usage[usage_key] = int(
            usage.get(
                usage_key,
                0
            )
        ) + 1

        save_usage(
            usage
        )


    # ==================================================
    # DELETE INPUT
    # ==================================================

    input_file.unlink(
        missing_ok=True
    )


    # ==================================================
    # SUCCESS
    # ==================================================

    return {

        "success": True,

        "job": job,

        "videos_used":
            usage[usage_key],

        "videos_remaining":
            max(
                0,
                50 - usage[usage_key]
            ),

        "download":
            f"/download/{job}"

    }


# ==================================================
# DOWNLOAD
# ==================================================

@APP.get("/download/{job}")
def download(job: str):

    if not job.isalnum():

        raise HTTPException(
            status_code=400,
            detail="Invalid job ID"
        )


    output_file = (
        OUTPUT_DIR
        /
        f"{job}.mp4"
    )


    if not output_file.exists():

        raise HTTPException(
            status_code=404,
            detail="Processed video not found"
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
