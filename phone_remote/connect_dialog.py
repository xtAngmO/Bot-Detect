"""หน้าต่างแรก: จับคู่ (ครั้งแรก) -> เชื่อมต่อ adb ข้ามเน็ต -> เลือกเครื่องแล้วเปิดหน้าต่างควบคุม.

มือถือที่เสียบ USB จะโผล่ในรายการขั้น ③ ทันที ไม่ต้องทำขั้น ① ②
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from adb import Adb, AdbError, Device, TailscalePeer, tailscale_peers
from settings import QUALITY_PRESETS, Settings
from ui_common import QSS, run_async
from window import RemoteWindow

_IP_IN_PARENS = re.compile(r"\(([^()]+)\)")


def split_host_port(text: str) -> Tuple[str, str]:
    """"pixel-7 (100.64.1.2)" -> ("100.64.1.2", ""),  "100.64.1.2:41235" -> ("100.64.1.2", "41235")."""
    text = text.strip()
    m = _IP_IN_PARENS.search(text)
    if m:
        text = m.group(1).strip()
    if text.count(":") == 1:
        host, port = text.split(":")
        return host.strip(), port.strip()
    return text, ""


def _card(title: str, hint: str = "") -> Tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(10)
    t = QLabel(title)
    t.setObjectName("step")
    lay.addWidget(t)
    if hint:
        h = QLabel(hint)
        h.setObjectName("dim")
        h.setWordWrap(True)
        lay.addWidget(h)
    return card, lay


def _row(*widgets: QWidget, stretch_index: int = -1) -> QWidget:
    row = QWidget()
    row.setObjectName("row")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for i, w in enumerate(widgets):
        lay.addWidget(w, 1 if i == stretch_index else 0)
    return row


class ConnectDialog(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.adb: Optional[Adb] = None
        self.windows: Dict[str, RemoteWindow] = {}
        self._devices: List[Device] = []
        self._busy = 0

        self.setWindowTitle("Phone Remote — เชื่อมต่อมือถือ")
        self.setStyleSheet(QSS)
        self.setMinimumWidth(460)
        self._build_ui()

        try:
            self.adb = Adb(settings.adb_path)
        except AdbError as e:
            self._log(str(e))
            for w in (self.pair_btn, self.connect_btn, self.refresh_btn, self.start_btn):
                w.setEnabled(False)
            return
        self.refresh()
        QTimer.singleShot(0, self._auto_reconnect)

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("ควบคุมมือถือ Android จากคอม")
        title.setObjectName("title")
        sub = QLabel("เสียบ USB, อยู่ Wi‑Fi วงเดียวกัน หรือข้ามเน็ตผ่าน Tailscale (ลงแอป Tailscale "
                     "บนมือถือและคอม ล็อกอินบัญชีเดียวกัน)")
        sub.setObjectName("dim")
        sub.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(sub)

        # ---- ต่อผ่านเน็ต ----
        net, net_lay = _card(
            "ต่อผ่านเน็ต — IP ของมือถือ",
            "เลือกมือถือจากรายชื่อ Tailscale (IP 100.x.x.x) หรือพิมพ์ IP เอง")
        self.host_combo = QComboBox()
        self.host_combo.setEditable(True)
        self.host_combo.lineEdit().setPlaceholderText("เช่น 100.101.102.103")
        self.host_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if self.settings.host:
            self.host_combo.setEditText(self.settings.host)
        self.peers_btn = QPushButton("โหลดรายชื่อ")
        self.peers_btn.setToolTip("ดึงรายชื่อเครื่องจาก Tailscale อีกครั้ง")
        self.peers_btn.clicked.connect(self.refresh_peers)
        net_lay.addWidget(_row(self.host_combo, self.peers_btn, stretch_index=0))

        step1 = QLabel("① จับคู่ (ทำครั้งแรกครั้งเดียว)")
        hint1 = QLabel("บนมือถือ: ตั้งค่า › ตัวเลือกสำหรับนักพัฒนาซอฟต์แวร์ › การแก้ไขข้อบกพร่องแบบไร้สาย "
                       "(Wireless debugging) › จับคู่อุปกรณ์ด้วยรหัสการจับคู่ — ใส่พอร์ตและรหัส 6 หลักที่ขึ้น")
        hint1.setObjectName("dim")
        hint1.setWordWrap(True)
        self.pair_port = QLineEdit()
        self.pair_port.setPlaceholderText("พอร์ตจับคู่")
        self.pair_port.setValidator(QIntValidator(1, 65535, self))
        self.pair_port.setFixedWidth(110)
        self.pair_code = QLineEdit()
        self.pair_code.setPlaceholderText("รหัส 6 หลัก")
        self.pair_code.setMaxLength(6)
        self.pair_code.setValidator(QIntValidator(0, 999999, self))
        self.pair_btn = QPushButton("จับคู่")
        self.pair_btn.clicked.connect(self.pair)
        net_lay.addWidget(step1)
        net_lay.addWidget(hint1)
        net_lay.addWidget(_row(self.pair_port, self.pair_code, self.pair_btn, stretch_index=1))

        step2 = QLabel("② เชื่อมต่อ")
        hint2 = QLabel("ใช้พอร์ตในหน้า \"การแก้ไขข้อบกพร่องแบบไร้สาย\" ตรง IP address & Port "
                       "(คนละพอร์ตกับตอนจับคู่ และเปลี่ยนทุกครั้งที่เปิดสวิตช์ใหม่)")
        hint2.setObjectName("dim")
        hint2.setWordWrap(True)
        self.connect_port = QLineEdit(self.settings.connect_port)
        self.connect_port.setPlaceholderText("พอร์ต")
        self.connect_port.setValidator(QIntValidator(1, 65535, self))
        self.connect_port.setFixedWidth(110)
        self.connect_btn = QPushButton("เชื่อมต่อ")
        self.connect_btn.clicked.connect(self.connect_network)
        spacer = QWidget()
        spacer.setObjectName("row")
        net_lay.addWidget(step2)
        net_lay.addWidget(hint2)
        net_lay.addWidget(_row(self.connect_port, self.connect_btn, spacer, stretch_index=2))
        root.addWidget(net)

        # ---- เลือกเครื่อง ----
        dev, dev_lay = _card("③ เลือกเครื่องแล้วเริ่มควบคุม", "มือถือที่เสียบ USB จะขึ้นที่นี่ทันที")
        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(96)
        self.device_list.itemDoubleClicked.connect(lambda _item: self.start())
        self.device_list.currentRowChanged.connect(lambda _row: self._update_start_enabled())
        dev_lay.addWidget(self.device_list)

        self.quality_combo = QComboBox()
        for key, (label, _opts) in QUALITY_PRESETS.items():
            self.quality_combo.addItem(label, key)
        idx = self.quality_combo.findData(self.settings.quality)
        self.quality_combo.setCurrentIndex(max(0, idx))
        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        dev_lay.addWidget(self.quality_combo)

        self.refresh_btn = QPushButton("รีเฟรช")
        self.refresh_btn.clicked.connect(self.refresh)
        self.start_btn = QPushButton("เริ่มควบคุม")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.start_btn.setEnabled(False)
        grow = QWidget()
        grow.setObjectName("row")
        dev_lay.addWidget(_row(self.refresh_btn, grow, self.start_btn, stretch_index=1))
        root.addWidget(dev)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(200)
        self.log_view.setFixedHeight(84)
        root.addWidget(self.log_view)

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _set_busy(self, busy: bool) -> None:
        self._busy += 1 if busy else -1
        enabled = self._busy == 0 and self.adb is not None
        for w in (self.pair_btn, self.connect_btn, self.refresh_btn):
            w.setEnabled(enabled)
        self.setCursor(Qt.CursorShape.ArrowCursor if enabled else Qt.CursorShape.BusyCursor)

    # ---- Tailscale ----
    def refresh_peers(self) -> None:
        self.peers_btn.setEnabled(False)
        run_async(tailscale_peers, self._on_peers, self._on_peers_error, self)

    def _on_peers(self, peers: List[TailscalePeer]) -> None:
        self.peers_btn.setEnabled(True)
        typed = self.host_combo.currentText()
        self.host_combo.clear()
        for peer in peers:
            self.host_combo.addItem(peer.label, peer.ip)
        self.host_combo.setEditText(typed)
        if not peers:
            self._log("ไม่พบเครื่องใน Tailscale (ยังไม่ได้ลง/ล็อกอิน Tailscale บนคอมนี้?) — พิมพ์ IP เองได้")

    def _on_peers_error(self, message: str) -> None:
        self.peers_btn.setEnabled(True)
        self._log(f"อ่านรายชื่อ Tailscale ไม่ได้: {message}")

    def _host(self) -> Tuple[str, str]:
        text = self.host_combo.currentText()
        idx = self.host_combo.findText(text)
        if idx >= 0 and self.host_combo.itemData(idx):
            return str(self.host_combo.itemData(idx)), ""
        return split_host_port(text)

    # ---- adb ----
    def refresh(self) -> None:
        if self.adb is None:
            return
        self._set_busy(True)
        adb = self.adb
        run_async(adb.devices, self._on_devices, self._on_adb_error, self)
        if self.host_combo.count() == 0:
            self.refresh_peers()

    def _on_devices(self, devices: List[Device], select: str = "") -> None:
        self._set_busy(False)
        current = self._selected_serial()
        self._devices = devices
        self.device_list.clear()
        for d in devices:
            item = QListWidgetItem(d.label)
            item.setData(Qt.ItemDataRole.UserRole, d.serial)
            self.device_list.addItem(item)
        want = select or current
        for i, d in enumerate(devices):
            if d.serial == want:
                self.device_list.setCurrentRow(i)
                break
        else:
            if devices:
                self.device_list.setCurrentRow(0)
        if not devices:
            self._log("ยังไม่พบมือถือ — เสียบ USB (เปิด USB debugging) หรือทำขั้น ① ② ด้านบน")
        self._update_start_enabled()

    def _on_adb_error(self, message: str) -> None:
        self._set_busy(False)
        self._log(message)

    def pair(self) -> None:
        host, port_in_host = self._host()
        port = self.pair_port.text().strip() or port_in_host
        code = self.pair_code.text().strip()
        if not host or not port or len(code) != 6:
            self._log("จับคู่: ต้องใส่ IP มือถือ, พอร์ตจับคู่ และรหัส 6 หลัก")
            return
        self._log(f"กำลังจับคู่ {host}:{port} ...")
        self._set_busy(True)
        adb = self.adb
        run_async(lambda: adb.pair(f"{host}:{port}", code), self._on_paired, self._on_adb_error, self)

    def _on_paired(self, _out: str) -> None:
        self._set_busy(False)
        self.pair_code.clear()
        self._log("จับคู่สำเร็จ ✓ — ต่อไปใส่พอร์ตในขั้น ② แล้วกดเชื่อมต่อ")
        self.connect_port.setFocus()

    def connect_network(self) -> None:
        host, port_in_host = self._host()
        port = self.connect_port.text().strip() or port_in_host
        if not host or not port:
            self._log("เชื่อมต่อ: ต้องใส่ IP มือถือและพอร์ต")
            return
        self.settings.host, self.settings.connect_port = host, port
        self.settings.save()
        self._connect(f"{host}:{port}")

    def _connect(self, address: str) -> None:
        self._log(f"กำลังเชื่อมต่อ {address} ...")
        self._set_busy(True)
        adb = self.adb

        def work() -> List[Device]:
            adb.connect(address)
            return adb.devices()

        run_async(work, lambda devices: self._on_connected(address, devices), self._on_adb_error, self)

    def _on_connected(self, address: str, devices: List[Device]) -> None:
        self._log(f"เชื่อมต่อ {address} แล้ว ✓")
        self._on_devices(devices, select=address)

    def _auto_reconnect(self) -> None:
        """เปิดโปรแกรมใหม่ -> ลองต่อเครื่องเดิมให้เอง (พอร์ต Wireless debugging อาจเปลี่ยนแล้ว ถ้าไม่ติดก็แค่แจ้ง)."""
        if self.settings.host and self.settings.connect_port and self.adb is not None:
            self._connect(f"{self.settings.host}:{self.settings.connect_port}")

    # ---- เริ่มควบคุม ----
    def _selected_serial(self) -> str:
        item = self.device_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ""

    def _update_start_enabled(self) -> None:
        serial = self._selected_serial()
        device = next((d for d in self._devices if d.serial == serial), None)
        self.start_btn.setEnabled(device is not None and device.state == "device")

    def _on_quality_changed(self) -> None:
        self.settings.quality = self.quality_combo.currentData()
        self.settings.save()

    def start(self) -> None:
        serial = self._selected_serial()
        device = next((d for d in self._devices if d.serial == serial), None)
        if device is None or self.adb is None:
            return
        if device.state == "unauthorized":
            self._log("มือถือยังไม่อนุญาตคอมเครื่องนี้ — กด \"อนุญาต\" (Allow) บนหน้าจอมือถือ แล้วกดรีเฟรช")
            return
        if device.state != "device":
            self._log(f"มือถือสถานะ {device.state} — ลองเชื่อมต่อใหม่")
            return
        existing = self.windows.get(serial)
        if existing is not None:
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return
        win = RemoteWindow(self.adb, serial, self.settings, label=device.model.replace("_", " ") or serial)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.closed.connect(lambda s: self.windows.pop(s, None))
        self.windows[serial] = win
        win.show()
        self._log(f"เปิดหน้าต่างควบคุม {device.label}")
