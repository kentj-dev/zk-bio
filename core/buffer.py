import time
from typing import List, Callable, Dict, Optional
from zk_bio.core.parsing import ParsedAttendance, AttendanceParser
from zk_bio.constants import QUEUE_PREVIEW_LIMIT, INACTIVITY_SECS, GRACE_SECS
from zk_bio.core.api import ApiGround

class BufferManager:
    """
    Owns buffering, idle-flush, and preview updates.
    If send_each_capture=True, it will call the API per item and only keep the buffer
    to power the UI preview (flush becomes a no-op for sending).
    """
    def __init__(
        self,
        emit_log: Callable[[str, str], None],
        on_preview: Callable[[int, List[str]], None],
        api: ApiGround,
        name_lookup: Dict[int, str],
        preview_limit: int = QUEUE_PREVIEW_LIMIT,
        inactivity_secs: int = INACTIVITY_SECS,
        grace_secs: int = GRACE_SECS,
        send_each_capture: bool = False,
    ):
        self.emit_log = emit_log
        self.on_preview = on_preview
        self.api = api
        self.name_lookup = name_lookup
        self.preview_limit = preview_limit
        self.inactivity_secs = inactivity_secs
        self.grace_secs = grace_secs
        self.send_each_capture = send_each_capture

        self._buffer: List[ParsedAttendance] = []
        self._last_activity_mono: Optional[float] = None

    def append(self, parsed: ParsedAttendance):
        self._buffer.append(parsed)
        self._last_activity_mono = time.monotonic()
        self.emit_log("buffer", f"queued (size={len(self._buffer)})")

        # Optional: call API immediately on each capture
        if self.send_each_capture:
            ok = self.api.send_one(parsed)
            if ok:
                self.emit_log("success", "Stamp sent.")
            else:
                self.emit_log("warn", "Send failed (realtime).")

        self._notify()

    def maybe_flush(self):
        if not self._buffer or self._last_activity_mono is None or self.send_each_capture:
            return
        idle = time.monotonic() - self._last_activity_mono
        if idle >= (self.inactivity_secs + self.grace_secs):
            self.flush(reason=f"idle {int(idle)}s")

    def flush(self, reason: str = "manual/stop"):
        if not self._buffer:
            return

        # If we are sending per-capture, flushing only clears UI buffer.
        if self.send_each_capture:
            self.emit_log("flush", f"Clearing UI buffer ({len(self._buffer)}) ({reason})...")
            self._buffer.clear()
            self._notify()
            return

        batch = list(self._buffer)
        self.emit_log("flush", f"Flushing {len(batch)} stamps ({reason})...")
        ok = self.api.send_batch(batch)
        if ok:
            self._buffer.clear()
            self.emit_log("success", "Buffer cleared.")
            self._notify()
        else:
            self.emit_log("warn", "Send failed; buffer retained for retry.")

    def size(self) -> int:
        return len(self._buffer)

    def _notify(self):
        items: List[str] = []
        for p in self._buffer[-self.preview_limit:]:
            items.append(AttendanceParser.queue_display(p, self.name_lookup))
        self.on_preview(len(self._buffer), items)
