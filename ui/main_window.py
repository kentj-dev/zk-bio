from html import escape
from datetime import datetime
from typing import Optional, List

from PyQt5 import QtCore, QtGui, QtWidgets

from zk_bio.constants import (
    APP_TITLE,
    LOGO_PATH,
    LOGO_ZKTECO_PATH,
)
from zk_bio.workers.zk_worker import ZKWorker

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

        top = self._build_top_banner()
        splitter = self._build_splitter()

        root = QtWidgets.QWidget()
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)
        root_layout.addWidget(top)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        self.status_bar = QtWidgets.QStatusBar(); self.setStatusBar(self.status_bar)
        self.status_pill = QtWidgets.QLabel("Disconnected")
        self.status_pill.setStyleSheet(self.STATUS_STYLE["disconnected"])
        self.status_bar.addPermanentWidget(self.status_pill)

        self._load_banner_logo(LOGO_PATH)
        self._load_zkteco_logo(LOGO_ZKTECO_PATH)

        self.connect_btn.clicked.connect(self.start_worker)
        self.disconnect_btn.clicked.connect(self.stop_worker)

    def _build_top_banner(self) -> QtWidgets.QWidget:
        top = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout(top)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(10)

        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setFixedHeight(40)
        self.logo_label.setScaledContents(True)

        self.title_label = QtWidgets.QLabel(APP_TITLE)
        font = self.title_label.font(); font.setPointSize(12); font.setBold(True)
        self.title_label.setFont(font)

        top_layout.addWidget(self.logo_label, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        top_layout.addWidget(self.title_label, 1, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        return top

    def _build_splitter(self) -> QtWidgets.QSplitter:
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)

        left = QtWidgets.QWidget()
        left_v = QtWidgets.QVBoxLayout(left)
        left_v.setContentsMargins(6, 6, 6, 6)
        left_v.setSpacing(8)

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
        self.omit_ping_chk.setChecked(True)

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

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAcceptRichText(True)
        self.log_view.setPlaceholderText("Logs will appear here...")
        right_layout.addWidget(self.log_view)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        return splitter

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

    def set_status(self, kind: str, text: str):
        style = self.STATUS_STYLE.get(kind, self.STATUS_STYLE["status"])
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(style)

    def _timestamp(self) -> str:
        from datetime import datetime
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

    @QtCore.pyqtSlot(int, list)
    def on_buffer_changed(self, count: int, items: list):
        self.queue_box.setTitle(f"Queue ({count})")
        self.queue_list.setUpdatesEnabled(False)
        self.queue_list.clear()
        if items:
            self.queue_list.addItems(items)
            self.queue_list.scrollToBottom()
        self.queue_list.setUpdatesEnabled(True)

    def set_controls_enabled(self, enabled: bool):
        self.ip_edit.setEnabled(enabled)
        self.port_spin.setEnabled(enabled)
        self.timeout_spin.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.force_udp_chk.setEnabled(enabled)
        self.omit_ping_chk.setEnabled(enabled)
        self.connect_btn.setEnabled(enabled)
        self.disconnect_btn.setEnabled(not enabled)

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

        # Toggle to send per-capture (True) or batch by idle-flush (False)
        send_each_capture = False  # set True if you want immediate API calls per stamp

        self.append_log("info", f"Connecting to {host}:{port}...")
        self.set_controls_enabled(False)
        self.set_status("connecting", "Connecting...")

        self.thread = QtCore.QThread(self)
        self.worker = ZKWorker(host, port, timeout, password, force_udp, omit_ping, send_each_capture=send_each_capture)
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

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.stop()
            if self.thread is not None:
                self.thread.quit()
                self.thread.wait(3000)
        event.accept()
