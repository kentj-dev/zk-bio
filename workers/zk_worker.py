from PyQt5 import QtCore
from zk import ZK

from typing import Dict, Optional

from zk_bio.core.api import ApiGround
from zk_bio.core.buffer import BufferManager
from zk_bio.core.parsing import AttendanceParser, ParsedAttendance
from zk_bio.core.users import UserDirectory
from zk_bio.constants import INACTIVITY_SECS, GRACE_SECS

class ZKWorker(QtCore.QObject):
    log_msg = QtCore.pyqtSignal(str, str)
    connected = QtCore.pyqtSignal()
    ready = QtCore.pyqtSignal()
    disconnected = QtCore.pyqtSignal()
    punch_line = QtCore.pyqtSignal(str)
    buffer_changed = QtCore.pyqtSignal(int, list)

    def __init__(self, host: str, port: int, timeout: int, password: int, force_udp: bool, omit_ping: bool, send_each_capture: bool = False):
        super().__init__()
        self.host = host
        self.port = port
        self.timeout = timeout
        self.password = password
        self.force_udp = force_udp
        self.omit_ping = omit_ping
        self.send_each_capture = send_each_capture

        self._running = True
        self._conn = None
        self._uid_to_name: Dict[int, str] = {}

        self.api = ApiGround(self._emit)
        # Buffer manager will be created after users are loaded (to pass name map)

        self.buffer: Optional[BufferManager] = None

    def _emit(self, kind: str, msg: str):
        self.log_msg.emit(kind, msg)

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self._emit("info", f"Connecting to {self.host}:{self.port} (timeout={self.timeout}s, UDP={self.force_udp}, omit_ping={self.omit_ping})...")
            zk = ZK(self.host, port=self.port, timeout=self.timeout,
                    password=self.password, force_udp=self.force_udp, ommit_ping=self.omit_ping)
            self._conn = zk.connect()
            self._emit("success", "Connected.")
            self.connected.emit()

            self._emit("status", "Disabling device...")
            self._conn.disable_device()

            self._emit("status", "Loading users...")
            self._uid_to_name = UserDirectory.build_uid_to_name_map(self._conn)
            self._emit("success", f"Loaded {len(self._uid_to_name)} users.")

            self.buffer = BufferManager(
                emit_log=self._emit,
                on_preview=lambda count, items: self.buffer_changed.emit(count, items),
                api=self.api,
                name_lookup=self._uid_to_name,
                inactivity_secs=INACTIVITY_SECS,
                grace_secs=GRACE_SECS,
                send_each_capture=self.send_each_capture,
            )

            self._emit("status", "Re-enabling device...")
            self._conn.enable_device()

            self.ready.emit()
            self._emit("status", "Ready. Listening for live captures...")

            while self._running:
                for attendance in self._conn.live_capture():
                    if not self._running:
                        break
                    if self.buffer:
                        self.buffer.maybe_flush()

                    if attendance is None:
                        continue

                    raw = str(attendance)
                    parsed = AttendanceParser.parse_text(raw) or AttendanceParser.parse_object(attendance)
                    if not parsed:
                        self._emit("warn", f"[unparsed] {raw}")
                        continue

                    self.punch_line.emit(AttendanceParser.punch_display(parsed, self._uid_to_name))
                    if self.buffer:
                        self.buffer.append(parsed)

                if not self._running:
                    break

        except Exception as e:
            self._emit("error", f"{e}")
        finally:
            try:
                if self.buffer and self.buffer.size() > 0:
                    self.buffer.flush(reason="disconnect/stop")
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
