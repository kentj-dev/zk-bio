from pathlib import Path
from typing import Dict
from zk_bio.utils import resource_path

PKG_ROOT = Path(__file__).resolve().parent
ASSETS_DIR = PKG_ROOT / "assets"

APP_TITLE = "CHEDRO XII - ZKTeco Biometric Live Capture"

# !! remove zk_bio if development mode
LOGO_PATH = resource_path("zk_bio/assets/ched.png")
LOGO_ZKTECO_PATH = resource_path("zk_bio/assets/zkt.png")

QUEUE_PREVIEW_LIMIT = 150

INACTIVITY_SECS = 10 * 60
GRACE_SECS = 2

TIME_PHASE_MAP: Dict[int, str] = {
    0: "check in",
    1: "check out",
    4: "overtime in",
    5: "overtime out",
}

MODE_MAP: Dict[int, str] = {
    2: "card",
}
