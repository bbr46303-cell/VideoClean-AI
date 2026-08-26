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


# =========================================================
# VIDEO CLEAN AI - BACKEND
# =========================================================

APP = FastAPI(
    title="VideoClean AI API"
)


# =========================================================
# CORS
# =========================================================

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# PATHS
# =========================================================

ROOT = Path(__file__).resolve().parent

FRONTEND = ROOT / "index.html"
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "outputs"
USAGE_FILE = ROOT / "usage.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# RAZORPAY
# =========================================================

RAZORPAY_KEY_ID = os.getenv(
    "RAZORPAY_KEY_ID",
    ""
).strip()

RAZORPAY_KEY_SECRET = os.getenv(
    "RAZORPAY_KEY_SECRET",
    ""
).strip()

RAZORPAY_PLAN_ID = os.getenv(
    "RAZORPAY_PLAN_ID",
    "plan_TU4y2sFEE55IWF"
).strip()

razorpay_client = None


if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    try:
        razorpay_client = razorpay.Client(
            auth=(
                RAZORPAY_KEY_ID,
                RAZORPAY_KEY_SECRET
            )
        )
        print("Razorpay client initialized.")

    except Exception as e:
        print(
            "Razorpay initialization error:",
            repr(e)
        )

else:
    print(
        "WARNING: Razorpay credentials are not configured."
    )


def razorpay_ready():
    return (
        razorpay_client is not None
        and bool(RAZORPAY_KEY_ID)
        and bool(RAZORPAY_KEY_SECRET)
        and bool(RAZORPAY_PLAN_ID)
    )


def razorpay_mode():

    if RAZORPAY_KEY_ID.startswith("rzp_test_"):
        return "test"

    if RAZORPAY_KEY_ID.startswith("rzp_live_"):
        return "live"

    return "unknown"


# =========================================================
# USAGE
# =========================================================

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

    except Exception as e:
        print(
            "Usage read error:",
            repr(e)
        )
        return {}


def save_usage(data):

    USAGE_FILE.write_text(
        json.dumps(
            data,
            indent=2
        ),
        encoding="utf-8"
    )


# =========================================================
# HOME
# =========================================================

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


# =========================================================
# HEALTH
# =========================================================

@APP.get("/health")
def health():

    return {
        "status": "ok",
        "service": "VideoClean AI",
        "razorpay_configured": razorpay_ready(),
        "razorpay_mode": razorpay_mode(),
        "plan_configured": bool(RAZORPAY_PLAN_ID)
    }


# =========================================================
# RAZORPAY CONFIG
# =========================================================

@APP.get("/api/razorpay-config")
def razorpay_config():

    if not RAZORPAY_KEY_ID:
        raise HTTPException(
            status_code=500,
            detail="Razorpay Key ID is not configured"
        )

    if not RAZORPAY_PLAN_ID:
        raise HTTPException(
            status_code=500,
            detail="Razorpay Plan ID is not configured"
        )

    return {
        "key_id": RAZORPAY_KEY_ID,
        "plan_id": RAZORPAY_PLAN_ID
    }


# =========================================================
# RAZORPAY TEST
# =========================================================

@APP.get("/api/razorpay-test")
def razorpay_test():

    if not razorpay_ready():
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Razorpay is not configured",
                "key_id_present": bool(RAZORPAY_KEY_ID),
                "secret_present": bool(RAZORPAY_KEY_SECRET),
                "plan_id": RAZORPAY_PLAN_ID
            }
        )

    try:

        plan = razorpay_client.plan.fetch(
            RAZORPAY_PLAN_ID
        )

        return {
            "success": True,
            "message": "Razorpay authentication successful",
            "mode": razorpay_mode(),
            "plan_id": plan.get("id"),
            "plan_name": plan.get(
                "item",
                {}
            ).get("name"),
            "plan_amount": plan.get(
                "item",
                {}
            ).get("amount")
        }

    except Exception as e:

        print(
            "Razorpay test error:",
            repr(e)
        )

        raise HTTPException(
            status_code=401,
            detail=(
                "Razorpay authentication failed. "
                "Check Key ID, Key Secret and Plan ID. "
                "They must belong to the same Razorpay mode."
            )
        )


# =========================================================
# CREATE SUBSCRIPTION
# =========================================================

@APP.post("/api/create-subscription")
async def create_subscription():

    if not razorpay_ready():
        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured correctly"
        )

    try:

        subscription = (
            razorpay_client.subscription.create(
                {
                    "plan_id": RAZORPAY_PLAN_ID,
                    "total_count": 12,
                    "quantity": 1,
                    "customer_notify": 1
                }
            )
        )

        print(
            "Subscription created:",
            subscription.get("id")
        )

        return {
            "success": True,
            "subscription_id": subscription["id"],
            "plan_id": RAZORPAY_PLAN_ID
        }

    except Exception as e:

        print(
            "Subscription creation error:",
            repr(e)
        )

        text = str(e).lower()

        if (
            "authentication" in text
            or "unauthorized" in text
            or "401" in text
        ):
            raise HTTPException(
                status_code=401,
                detail="Razorpay authentication failed"
            )

        raise HTTPException(
            status_code=500,
            detail="Unable to create Razorpay subscription"
        )


# =========================================================
# VERIFY SUBSCRIPTION
# =========================================================

@APP.post("/api/verify-subscription")
async def verify_subscription(data: dict):

    if not razorpay_ready():
        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
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

    if not payment_id:
        raise HTTPException(
            status_code=400,
            detail="Missing razorpay_payment_id"
        )

    if not subscription_id:
        raise HTTPException(
            status_code=400,
            detail="Missing razorpay_subscription_id"
        )

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing razorpay_signature"
        )

    # Verify Razorpay signature
    generated_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{payment_id}|{subscription_id}".encode("utf-8"),
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

    # Verify subscription exists
    try:

        subscription = (
            razorpay_client.subscription.fetch(
                subscription_id
            )
        )

    except Exception as e:

        print(
            "Subscription fetch error:",
            repr(e)
        )

        raise HTTPException(
            status_code=404,
            detail="Unable to find Razorpay subscription"
        )

    status = subscription.get("status")

    if status not in [
        "authenticated",
        "active"
    ]:
        raise HTTPException(
            status_code=400,
            detail=(
                "Subscription is not active. "
                f"Current status: {status}"
            )
        )

    return {
        "success": True,
        "message": "Subscription verified successfully",
        "subscription_id": subscription_id,
        "payment_id": payment_id,
        "status": status
    }


# =========================================================
# SUBSCRIPTION STATUS
# =========================================================

@APP.get("/api/subscription/{subscription_id}")
def subscription_status(subscription_id: str):

    if not razorpay_ready():
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

    except Exception as e:

        print(
            "Subscription status error:",
            repr(e)
        )

        raise HTTPException(
            status_code=404,
            detail="Subscription not found"
        )

    status = subscription.get("status")

    current_start = subscription.get(
        "current_start"
    )

    current_end = subscription.get(
        "current_end"
    )

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

    return {
        "subscription_id": subscription_id,
        "status": status,
        "videos_used": videos_used,
        "videos_remaining": max(
            0,
            50 - videos_used
        ),
        "monthly_limit": 50,
        "max_minutes": 10,
        "current_start": current_start,
        "current_end": current_end
    }


# =========================================================
# VIDEO DURATION
# =========================================================

def get_video_duration(file_path: Path):

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
            repr(e)
        )

        return None


# =========================================================
# PROCESS VIDEO
# =========================================================

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

    # -----------------------------------------------------
    # RAZORPAY CHECK
    # -----------------------------------------------------

    if not razorpay_ready():
        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
        )

    # -----------------------------------------------------
    # SUBSCRIPTION CHECK
    # -----------------------------------------------------

    try:

        subscription = (
            razorpay_client.subscription.fetch(
                subscription_id
            )
        )

    except Exception as e:

        print(
            "Subscription validation error:",
            repr(e)
        )

        raise HTTPException(
            status_code=403,
            detail="Invalid subscription"
        )

    subscription_status = subscription.get(
        "status"
    )

    if subscription_status != "active":

        raise HTTPException(
            status_code=403,
            detail=(
                "Your monthly subscription "
                "is not active"
            )
        )

    # -----------------------------------------------------
    # BILLING CYCLE
    # -----------------------------------------------------

    current_start = subscription.get(
        "current_start"
    )

    cycle_key = str(
        current_start or "default"
    )

    usage_key = (
        f"{subscription_id}_{cycle_key}"
    )

    # -----------------------------------------------------
    # MONTHLY LIMIT
    # -----------------------------------------------------

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
                detail=(
                    "Monthly limit reached. "
                    "You can process up to "
                    "50 videos per month."
                )
            )

    # -----------------------------------------------------
    # JOB
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # SAVE UPLOAD
    # -----------------------------------------------------

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
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to save uploaded video"
        )

    # -----------------------------------------------------
    # DURATION
    # -----------------------------------------------------

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
            detail="Maximum video length is 10 minutes."
        )

    # -----------------------------------------------------
    # VIDEO FILTERS
    # -----------------------------------------------------

    video_filters = []

    if enhance:

        video_filters.append(
            "eq=contrast=1.03:saturation=1.03"
        )

    if (
        w > 0
        and h > 0
    ):

        video_filters.append(
            f"delogo="
            f"x={x}:"
            f"y={y}:"
            f"w={w}:"
            f"h={h}:"
            f"show=0"
        )

    # -----------------------------------------------------
    # FFMPEG
    # -----------------------------------------------------

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_file)
    ]

    if video_filters:

        command += [
            "-vf",
            ",".join(video_filters)
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

    # -----------------------------------------------------
    # RUN FFMPEG
    # -----------------------------------------------------

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

        error_text = e.stderr.decode(
            errors="ignore"
        )

        print(
            "FFmpeg ERROR:",
            error_text[-3000:]
        )

        raise HTTPException(
            status_code=500,
            detail="Video processing failed"
        )

    except Exception as e:

        input_file.unlink(
            missing_ok=True
        )

        print(
            "FFmpeg unexpected error:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Video processing failed"
        )

    # -----------------------------------------------------
    # OUTPUT CHECK
    # -----------------------------------------------------

    if not output_file.exists():

        input_file.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=500,
            detail="Processed video was not created"
        )

    # -----------------------------------------------------
    # COUNT VIDEO
    # -----------------------------------------------------

    with usage_lock:

        usage = load_usage()

        videos_used_after = (
            int(
                usage.get(
                    usage_key,
                    0
                )
            ) + 1
        )

        usage[usage_key] = (
            videos_used_after
        )

        save_usage(
            usage
        )

    # -----------------------------------------------------
    # DELETE INPUT
    # -----------------------------------------------------

    input_file.unlink(
        missing_ok=True
    )

    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    return {
        "success": True,
        "job": job,
        "videos_used": videos_used_after,
        "videos_remaining": max(
            0,
            50 - 
