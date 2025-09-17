import sys
from pathlib import Path

def resource_path(rel: str) -> str:
    """
    Returns the correct path for resources (icons, images, etc.)
    Works both in dev mode and in a PyInstaller frozen exe.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str((base / rel).resolve())