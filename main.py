import sys
import re
import time
import json
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Callable
from html import escape
from datetime import datetime

from PyQt5 import QtCore, QtWidgets, QtGui
from zk import ZK

# ---------------------------
# Config & Constants
# ---------------------------

APP_TITLE = "CHEDRO XII - ZKTeco Biometric Live Capture"
LOGO_PATH = "assets/ched.png"
LOGO_ZKTECO_PATH = "assets/zkt.png"

QUEUE_PREVIEW_LIMIT = 150

TIME_PHASE_MAP: Dict[int, str] = {
    0: "check in",
    1: "check out",
    4: "overtime in",
    5: "overtime out",
}

MODE_MAP: Dict[int, str] = {
    2: "card",
}

# ---------------------------
# Data & Parsing
# ---------------------------

@dataclass
class ParsedAttendance:
    biometric_id: int
    date: str         # YYYY-MM-DD
    time: str         # HH:MM:SS
    mode_of_attendance: int
    time_phase: int


class AttendanceParser:
    """Pure functions for parsing/formatting attendance."""
    ATTENDANCE_RE = re.compile(
        r"^<Attendance>:\s*(?P<uid>\d+)\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s*\(\s*(?P<mode>\d+)\s*,\s*(?P<phase>\d+)\s*\)\s*$"
    )

    @staticmethod
    def parse_text(raw: str) -> Optional[ParsedAttendance]:
        m = AttendanceParser.ATTENDANCE_RE.match(raw.strip())
        if not m:
            return None
        return ParsedAttendance(
            biometric_id=int(m.group("uid")),
            date=m.group("date"),
            time=m.group("time"),
            mode_of_attendance=int(m.group("mode")),
            time_phase=int(m.group("phase")),
        )

    @staticmethod
    def parse_object(attendance_obj) -> Optional[ParsedAttendance]:
        """Fallback for SDK object when text format doesn't match."""
        try:
            uid = int(getattr(attendance_obj, "user_id", getattr(attendance_obj, "uid")))
            ts = getattr(attendance_obj, "timestamp")
            mode = int(getattr(attendance_obj, "status", getattr(attendance_obj, "mode", -1)))
            phase = int(getattr(attendance_obj, "punch", getattr(attendance_obj, "time_phase", -1)))
            date = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts).split(" ")[0]
            time_s = ts.strftime("%H:%M:%S") if hasattr(ts, "strftime") else str(ts).split(" ")[1]
            return ParsedAttendance(uid, date, time_s, mode, phase)
        except Exception:
            return None

    @staticmethod
    def phase_text(phase: int) -> str:
        return TIME_PHASE_MAP.get(phase, f"phase {phase}")

    @staticmethod
    def mode_text(mode: int) -> str:
        return MODE_MAP.get(mode, f"mode {mode}")

    @staticmethod
    def punch_display(parsed: ParsedAttendance, name_lookup: Dict[int, str]) -> str:
        name = name_lookup.get(parsed.biometric_id, "Unknown User")
        return (
            f"[{name}] ({parsed.biometric_id}) - {parsed.date} at {parsed.time} - "
            f"{AttendanceParser.mode_text(parsed.mode_of_attendance)} - {AttendanceParser.phase_text(parsed.time_phase)}"
        )

    @staticmethod
    def queue_display(parsed: ParsedAttendance, name_lookup: Dict[int, str]) -> str:
        name = name_lookup.get(parsed.biometric_id, "Unknown User")
        return (
            f"[{name}] ({parsed.biometric_id}) - {parsed.date} {parsed.time} - "
            f"{AttendanceParser.mode_text(parsed.mode_of_attendance)} - {AttendanceParser.phase_text(parsed.time_phase)}"
        )


# ---------------------------
# External resources (users, API)
# ---------------------------

class UserDirectory:
    @staticmethod
    def build_uid_to_name_map(conn) -> Dict[int, str]:
        uid_to_name: Dict[int, str] = {}
        for user in conn.get_users():
            name = (user.name or "").strip()
            if not name:
                name = (getattr(user, "user_id", "") or "").strip()
            if not name:
                name = f"UID {user.uid}"
            uid_to_name[user.uid] = name
        return uid_to_name


class ApiGround:
    """Pluggable API surface. Currently prints; return True to indicate success."""
    def __init__(self, emit_log: Callable[[str, str], None]):
        self.emit_log = emit_log

    def send_batch(self, batch: List[ParsedAttendance]) -> bool:
        payload = [asdict(item) for item in batch]
        self.emit_log("api", f"Sending {len(payload)} stamps...")
        self.emit_log("api", f"Payload: {json.dumps(payload, ensure_ascii=False)}")
        return True  # Simulate OK


# ---------------------------
# Buffered Queue
# ---------------------------

class BufferManager:
    """Owns buffering, idle-flush, and preview updates."""
    def __init__(
        self,
        emit_log: Callable[[str, str], None],
        on_preview: Callable[[int, List[str]], None],
        api: ApiGround,
        preview_limit: int = QUEUE_PREVIEW_LIMIT,
        inactivity_secs: int = 10 * 60,
        grace_secs: int = 2,
    ):
        self.emit_log = emit_log
        self.on_preview = on_preview
        self.api = api
        self.preview_limit = preview_limit
        self.inactivity_secs = inactivity_secs
        self.grace_secs = grace_secs

        self._buffer: List[ParsedAttendance] = []
        self._last_activity_mono: Optional[float] = None

    def append(self, parsed: ParsedAttendance, name_lookup: Dict[int, str]):
        self._buffer.append(parsed)
        self._last_activity_mono = time.monotonic()
        self.emit_log("buffer", f"queued (size={len(self._buffer)})")
        self._notify(name_lookup)

    def maybe_flush(self, name_lookup: Dict[int, str]):
        if not self._buffer or self._last_activity_mono is None:
            return
        idle = time.monotonic() - self._last_activity_mono
        if idle >= (self.inactivity_secs + self.grace_secs):
            self.flush(name_lookup, reason=f"idle {int(idle)}s")

    def flush(self, name_lookup: Dict[int, str], reason: str = "manual/stop"):
        if not self._buffer:
            return
        batch = list(self._buffer)
        self.emit_log("flush", f"Flushing {len(batch)} stamps ({reason})...")
        ok = self.api.send_batch(batch)
        if ok:
            self._buffer.clear()
            self.emit_log("success", "Buffer cleared.")
            self._notify(name_lookup)
        else:
            self.emit_log("warn", "Send failed; buffer retained for retry.")

    def size(self) -> int:
        return len(self._buffer)

    def _notify(self, name_lookup: Dict[int, str]):
        items: List[str] = []
        for p in self._buffer[-self.preview_limit:]:
            items.append(AttendanceParser.queue_display(p, name_lookup))
        self.on_preview(len(self._buffer), items)


# ---------------------------
# Worker (now composed of helpers)
# ---------------------------

class ZKWorker(QtCore.QObject):
    log_msg = QtCore.pyqtSignal(str, str)
    connected = QtCore.pyqtSignal()
    ready = QtCore.pyqtSignal()
    disconnected = QtCore.pyqtSignal()
    punch_line = QtCore.pyqtSignal(str)
    buffer_changed = QtCore.pyqtSignal(int, list)

    def __init__(self, host: str, port: int, timeout: int, password: int, force_udp: bool, omit_ping: bool):
        super().__init__()
        self.host = host
        self.port = port
        self.timeout = timeout
        self.password = password
        self.force_udp = force_udp
        self.omit_ping = omit_ping

        self._running = True
        self._conn = None
        self._uid_to_name: Dict[int, str] = {}

        # Compose helpers
        self.api = ApiGround(self._emit)
        self.buffer = BufferManager(
            emit_log=self._emit,
            on_preview=lambda count, items: self.buffer_changed.emit(count, items),
            api=self.api,
        )

    # -- Logging bridge
    def _emit(self, kind: str, msg: str):
        self.log_msg.emit(kind, msg)

    # -- Lifecycle
    @QtCore.pyqtSlot()
    def run(self):
        try:
            self._emit(
                "info",
                f"Connecting to {self.host}:{self.port} (timeout={self.timeout}s, UDP={self.force_udp}, omit_ping={self.omit_ping})..."
            )
            zk = ZK(
                self.host,
                port=self.port,
                timeout=self.timeout,
                password=self.password,
                force_udp=self.force_udp,
                ommit_ping=self.omit_ping,  # NOTE: library uses 'ommit_ping'
            )
            self._conn = zk.connect()
            self._emit("success", "Connected.")
            self.connected.emit()

            self._emit("status", "Disabling device...")
            self._conn.disable_device()

            self._emit("status", "Loading users...")
            self._uid_to_name = UserDirectory.build_uid_to_name_map(self._conn)
            self._emit("success", f"Loaded {len(self._uid_to_name)} users.")

            self._emit("status", "Re-enabling device...")
            self._conn.enable_device()

            self.ready.emit()
            self._emit("status", "Ready. Listening for live captures...")

            while self._running:
                for attendance in self._conn.live_capture():
                    self.buffer.maybe_flush(self._uid_to_name)
                    if not self._running:
                        break
                    if attendance is None:
                        continue

                    # Prefer text parse; fallback to object parse
                    raw = str(attendance)
                    parsed = AttendanceParser.parse_text(raw) or AttendanceParser.parse_object(attendance)
                    if not parsed:
                        self._emit("warn", f"[unparsed] {raw}")
                        continue

                    # UI punch line + queue append
                    self.punch_line.emit(AttendanceParser.punch_display(parsed, self._uid_to_name))
                    self.buffer.append(parsed, self._uid_to_name)

                if not self._running:
                    break

        except Exception as e:
            self._emit("error", f"{e}")
        finally:
            try:
                if self.buffer.size() > 0:
                    self.buffer.flush(self._uid_to_name, reason="disconnect/stop")
                if self._conn:
                    self._emit("status", "Cleaning up device...")
                    try:
                        self._conn.enable_device()
                    except Exception:
                        pass
                    self._conn.disconnect()
                    self._emit("info", "Disconnected.")
                    self.disconnected.emit()
            except Exception as e:
                self._emit("error", f"Cleanup error: {e}")

    def stop(self):
        self._running = False


# ---------------------------
# Main Window (unchanged behavior, cleaner helpers)
# ---------------------------

class MainWindow(QtWidgets.QMainWindow):
    COLOR_MAP = {
        "info":    "#2563eb",
        "status":  "#7c3aed",
        "success": "#16a34a",
        "warn":    "#d97706",
        "error":   "#dc2626",
        "punch":   "#0d9488",
        "api":     "#374151",
        "buffer":  "#6b7280",
        "flush":   "#8b5cf6",
    }

    STATUS_STYLE = {
        "connecting":  "background-color:#FEF3C7; color:#92400e; font-weight:600; padding:3px 10px; border-radius:6px;",
        "connected":   "background-color:#DCFCE7; color:#166534; font-weight:600; padding:3px 10px; border-radius:6px;",
        "ready":       "background-color:#E0F2FE; color:#0369a1; font-weight:600; padding:3px 10px; border-radius:6px;",
        "disconnected":"background-color:#FEE2E2; color:#991B1B; font-weight:600; padding:3px 10px; border-radius:6px;",
        "status":      "background-color:#F3E8FF; color:#6b21a8; font-weight:600; padding:3px 10px; border-radius:6px;",
        "error":       "background-color:#FEE2E2; color:#991B1B; font-weight:700; padding:3px 10px; border-radius:6px;",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(980, 620)
        self.setStyleSheet("font-family: Arial, sans-serif; font-size: 10pt;")

        self.thread: Optional[QtCore.QThread] = None
        self.worker: Optional[ZKWorker] = None

        # Build UI
        top = self._build_top_banner()
        splitter = self._build_splitter()

        # Root
        root = QtWidgets.QWidget()
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)
        root_layout.addWidget(top)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        # Status bar
        self.status_bar = QtWidgets.QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_pill = QtWidgets.QLabel("Disconnected")
        self.status_pill.setStyleSheet(self.STATUS_STYLE["disconnected"])
        self.status_bar.addPermanentWidget(self.status_pill)

        # Load logos
        self._load_banner_logo(LOGO_PATH)
        self._load_zkteco_logo(LOGO_ZKTECO_PATH)

        # Events
        self.connect_btn.clicked.connect(self.start_worker)
        self.disconnect_btn.clicked.connect(self.stop_worker)

    # ----- UI builders -----
    def _build_top_banner(self) -> QtWidgets.QWidget:
        top = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout(top)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(10)

        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setFixedHeight(40)
        self.logo_label.setScaledContents(True)

        self.title_label = QtWidgets.QLabel(APP_TITLE)
        font = self.title_label.font()
        font.setPointSize(12)
        font.setBold(True)
        self.title_label.setFont(font)

        top_layout.addWidget(self.logo_label, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        top_layout.addWidget(self.title_label, 1, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        return top

    def _build_splitter(self) -> QtWidgets.QSplitter:
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)

        left = self._build_left_panel()
        right = self._build_right_logs()

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        return splitter

    def _build_left_panel(self) -> QtWidgets.QWidget:
        left = QtWidgets.QWidget()
        left_v = QtWidgets.QVBoxLayout(left)
        left_v.setContentsMargins(6, 6, 6, 6)
        left_v.setSpacing(8)

        # Device box
        self.creds_box = QtWidgets.QGroupBox("ZKTeco Device")
        left_form = QtWidgets.QFormLayout(self.creds_box)
        left_form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.ip_edit = QtWidgets.QLineEdit("192.168.1.201")
        self.port_spin = QtWidgets.QSpinBox(); self.port_spin.setRange(1, 65535); self.port_spin.setValue(4370)
        self.timeout_spin = QtWidgets.QSpinBox(); self.timeout_spin.setRange(1, 120); self.timeout_spin.setValue(5)
        self.password_edit = QtWidgets.QLineEdit("123456")
        self.password_edit.setPlaceholderText("Comm key / password (integer)")
        self.password_edit.setValidator(QtGui.QIntValidator(0, 2_147_483_647, self))
        self.force_udp_chk = QtWidgets.QCheckBox("Force UDP")
        self.omit_ping_chk = QtWidgets.QCheckBox("Omit ping")

        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.disconnect_btn = QtWidgets.QPushButton("Disconnect"); self.disconnect_btn.setEnabled(False)
        btn_row = QtWidgets.QHBoxLayout(); btn_row.addWidget(self.connect_btn); btn_row.addWidget(self.disconnect_btn)

        left_form.addRow("IP", self.ip_edit)
        left_form.addRow("Port", self.port_spin)
        left_form.addRow("Timeout (s)", self.timeout_spin)
        left_form.addRow("Password", self.password_edit)
        left_form.addRow("", self.force_udp_chk)
        left_form.addRow("", self.omit_ping_chk)
        btn_row_w = QtWidgets.QWidget(); btn_row_w.setLayout(btn_row)
        left_form.addRow("", btn_row_w)

        # Queue box
        self.queue_box = QtWidgets.QGroupBox("Queue (0)")
        q_layout = QtWidgets.QVBoxLayout(self.queue_box)
        q_layout.setContentsMargins(8, 6, 8, 6)
        q_layout.setSpacing(6)

        self.queue_list = QtWidgets.QListWidget()
        self.queue_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.queue_list.setAlternatingRowColors(True)
        self.queue_list.setUniformItemSizes(True)
        self.queue_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.queue_list.setMinimumHeight(120)
        q_layout.addWidget(self.queue_list)

        # ZKTeco logo + footer
        self.zkteco_logo = QtWidgets.QLabel()
        self.zkteco_logo.setAlignment(QtCore.Qt.AlignCenter)
        self.zkteco_logo.setFixedHeight(80)
        self.zkteco_logo.setScaledContents(True)

        self.dev = QtWidgets.QLabel('© All rights reserved. CHEDRO XII 2025')
        font = self.dev.font(); font.setPointSize(8); font.setBold(True); self.dev.setFont(font)

        left_v.addWidget(self.creds_box)
        left_v.addWidget(self.queue_box)
        left_v.addStretch(1)
        left_v.addWidget(self.zkteco_logo, 0, QtCore.Qt.AlignHCenter)
        left_v.addWidget(self.dev, 0, QtCore.Qt.AlignHCenter)
        return left

    def _build_right_logs(self) -> QtWidgets.QWidget:
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAcceptRichText(True)
        self.log_view.setPlaceholderText("Logs will appear here...")
        right_layout.addWidget(self.log_view)
        return right

    # ----- Logo helpers -----
    def _load_banner_logo(self, path: str):
        pix = QtGui.QPixmap(path)
        if not pix.isNull():
            banner_pix = pix.scaledToHeight(self.logo_label.height(), QtCore.Qt.SmoothTransformation)
            self.logo_label.setPixmap(banner_pix)
            self.setWindowIcon(QtGui.QIcon(pix))
            self.append_log("info", f"Loaded banner logo: {path}")
        else:
            self.logo_label.setText("")
            self.append_log("warn", f"Banner logo not found: {path}")

    def _load_zkteco_logo(self, path: str):
        pix = QtGui.QPixmap(path)
        if not pix.isNull():
            logo_pix = pix.scaledToHeight(self.zkteco_logo.height(), QtCore.Qt.SmoothTransformation)
            self.zkteco_logo.setPixmap(logo_pix)
            self.append_log("info", f"Loaded ZKTeco logo: {path}")
        else:
            self.zkteco_logo.setText("")
            self.append_log("warn", f"ZKTeco logo not found: {path}")

    # ----- Status helpers -----
    def set_status(self, kind: str, text: str):
        style = self.STATUS_STYLE.get(kind, self.STATUS_STYLE["status"])
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(style)

    # ----- UI helpers -----
    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def append_log(self, kind: str, message: str):
        if kind in ("error",):
            self.set_status("error", "Error")
        ts = self._timestamp()
        ts_html = f'<span style="color:#9ca3af;">[{escape(ts)}]</span>'
        color = self.COLOR_MAP.get(kind, "#111827")
        msg_html = f'<span style="color:{color};">{escape(message)}</span>'
        html_line = f'<div>{ts_html} : {msg_html}</div><br>'
        cursor = self.log_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertHtml(html_line)
        self.log_view.ensureCursorVisible()

    def append_punch(self, line: str):
        self.append_log("punch", line)

    def set_controls_enabled(self, enabled: bool):
        self.ip_edit.setEnabled(enabled)
        self.port_spin.setEnabled(enabled)
        self.timeout_spin.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.force_udp_chk.setEnabled(enabled)
        self.omit_ping_chk.setEnabled(enabled)
        self.connect_btn.setEnabled(enabled)
        self.disconnect_btn.setEnabled(not enabled)

    # ----- Queue UI updates (slot) -----
    @QtCore.pyqtSlot(int, list)
    def on_buffer_changed(self, count: int, items: List[str]):
        self.queue_box.setTitle(f"Queue ({count})")
        self.queue_list.setUpdatesEnabled(False)
        self.queue_list.clear()
        if items:
            self.queue_list.addItems(items)
            self.queue_list.scrollToBottom()
        self.queue_list.setUpdatesEnabled(True)

    # ----- Thread control -----
    def start_worker(self):
        if self.worker is not None:
            self.append_log("warn", "Already connected/connecting.")
            return

        host = self.ip_edit.text().strip()
        port = int(self.port_spin.value())
        timeout = int(self.timeout_spin.value())
        password_text = self.password_edit.text().strip()
        password = int(password_text) if password_text else 0
        force_udp = self.force_udp_chk.isChecked()
        omit_ping = self.omit_ping_chk.isChecked()

        self.append_log("info", f"Connecting to {host}:{port}...")
        self.set_controls_enabled(False)
        self.set_status("connecting", "Connecting...")

        self.thread = QtCore.QThread(self)
        self.worker = ZKWorker(host, port, timeout, password, force_udp, omit_ping)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log_msg.connect(self.append_log)
        self.worker.punch_line.connect(self.append_punch)
        self.worker.buffer_changed.connect(self.on_buffer_changed)
        self.worker.connected.connect(lambda: self.set_status("connected", "Connected"))
        self.worker.ready.connect(lambda: self.set_status("ready", "Ready"))
        self.worker.disconnected.connect(self.on_disconnected)
        self.thread.finished.connect(self.cleanup_thread_objects)

        self.thread.start()

    def stop_worker(self):
        if self.worker is None:
            self.append_log("warn", "Not connected.")
            return
        self.set_status("error", "Stopping...")
        self.append_log("status", "Stopping...")
        try:
            self.worker.stop()
        except Exception as e:
            self.append_log("error", f"Stop error: {e}")

    def on_disconnected(self):
        self.append_log("info", "Status: disconnected")
        self.set_controls_enabled(True)
        self.set_status("disconnected", "Disconnected")
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
        self.cleanup_thread_objects()

    def cleanup_thread_objects(self):
        self.worker = None
        self.thread = None

    # ----- Close handling -----
    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.stop()
            if self.thread is not None:
                self.thread.quit()
                self.thread.wait(3000)
        event.accept()


# ---------------------------
# App bootstrap
# ---------------------------

def main():
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
