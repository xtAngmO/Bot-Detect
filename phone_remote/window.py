"""หน้าต่างควบคุมมือถือ: จอมือถือเต็มหน้าต่าง + แถบปุ่มแนวตั้งด้านขวา + แถบสถานะ.

เมาส์บนภาพ:  คลิกซ้าย = แตะ, ลาก = ปัด/เลื่อน, Ctrl+ลาก = ถ่างสองนิ้ว (ซูม), ล้อเมาส์ = เลื่อน,
             คลิกขวา = ย้อนกลับ (หรือเปิดจอถ้าจอดับ), คลิกกลาง = หน้าแรก
คีย์บอร์ด:   พิมพ์ได้เลย (ภาษาไทยส่งผ่าน clipboard ให้อัตโนมัติ), Esc = ย้อนกลับ, Ctrl+V = วางข้อความจากคอม

คลิกจากโปรแกรมอื่น (เช่นบอทเรียงเลขที่คลิกด้วย SendInput) ก็เข้าทางเดียวกับเมาส์จริง จึงใช้บอทกับ
มือถือจริงผ่านหน้าต่างนี้ได้
"""
from __future__ import annotations

import datetime
import os
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QSizePolicy, QToolBar, QWidget

import icons
import keymap
import protocol
from adb import Adb
from scrcpy_server import ScrcpySession, StreamOptions
from settings import Settings
from stream import ControlChannel, VideoReceiver
from ui_common import QSS, run_async

TOOLBAR_WIDTH = 52


def fit_rect(area: QSize, video: QSize) -> QRect:
    """สี่เหลี่ยมที่ใหญ่สุดใน area ที่คงสัดส่วนของ video ไว้ (วางกลาง)."""
    if video.width() <= 0 or video.height() <= 0 or area.width() <= 0 or area.height() <= 0:
        return QRect()
    scale = min(area.width() / video.width(), area.height() / video.height())
    w = max(1, round(video.width() * scale))
    h = max(1, round(video.height() * scale))
    return QRect((area.width() - w) // 2, (area.height() - h) // 2, w, h)


def map_to_video(pos: QPoint, rect: QRect, video: QSize) -> Optional[QPoint]:
    """พิกัดบน widget -> พิกัดบนวิดีโอ (ที่ server ต้องการ). นอกภาพคืน None."""
    if rect.isEmpty() or not rect.contains(pos):
        return None
    x = (pos.x() - rect.x()) * video.width() / rect.width()
    y = (pos.y() - rect.y()) * video.height() / rect.height()
    return QPoint(min(int(x), video.width() - 1), min(int(y), video.height() - 1))


class ScreenView(QWidget):
    """แสดงภาพจอมือถือ และแปลงเมาส์/ล้อ/คีย์บอร์ดเป็นคำสั่งส่งผ่าน send()."""

    display_size_changed = Signal(int, int)

    def __init__(self, send: Callable[[bytes], bool], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._send = send
        self._image: Optional[QImage] = None
        self._video = QSize(0, 0)
        self._message = "กำลังเชื่อมต่อ ..."
        self._pressed = False
        self._pinch = False
        self._last_video_pos = QPoint()
        self.on_key_text: Callable[[str], None] = lambda _t: None
        self.on_paste: Callable[[], None] = lambda: None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 160)

    # ---- สถานะ ----
    @property
    def video_size(self) -> QSize:
        return QSize(self._video)

    def set_video_size(self, width: int, height: int) -> None:
        self._video = QSize(width, height)
        self._release_all()
        self._emit_display_size()
        self.update()

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._message = ""
        self.update()

    def set_message(self, message: str) -> None:
        self._message = message
        self._release_all()
        self.update()

    def video_rect(self) -> QRect:
        return fit_rect(self.size(), self._video)

    def _emit_display_size(self) -> None:
        r = self.video_rect()
        if not r.isEmpty():
            ratio = self.devicePixelRatioF()
            self.display_size_changed.emit(round(r.width() * ratio), round(r.height() * ratio))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._emit_display_size()

    # ---- วาด ----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#050506"))
        rect = self.video_rect()
        if self._image is not None and not rect.isEmpty():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(rect, self._image)
        if self._message:
            if self._image is not None:
                p.fillRect(self.rect(), QColor(5, 5, 6, 200))
            p.setPen(QColor("#a0a0a0"))
            p.drawText(self.rect().adjusted(24, 24, -24, -24),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message)
        p.end()

    # ---- แตะ/ลาก ----
    def _touch(self, action: int, pointer_id: int, pos: QPoint) -> None:
        self._send(protocol.inject_touch(action, pointer_id, pos.x(), pos.y(),
                                         self._video.width(), self._video.height()))

    def _mirror(self, pos: QPoint) -> QPoint:
        """นิ้วที่สองของท่าซูม — สะท้อนรอบจุดกึ่งกลางจอ (ท่าเดียวกับ scrcpy Ctrl+ลาก)."""
        return QPoint(self._video.width() - 1 - pos.x(), self._video.height() - 1 - pos.y())

    def _release_all(self) -> None:
        if self._pressed:
            self._touch(protocol.ACTION_UP, protocol.POINTER_ID_GENERIC_FINGER, self._last_video_pos)
            if self._pinch:
                self._touch(protocol.ACTION_UP, protocol.POINTER_ID_VIRTUAL_FINGER,
                            self._mirror(self._last_video_pos))
        self._pressed = self._pinch = False

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus()
        if self._message:
            return
        button = event.button()
        if button == Qt.MouseButton.RightButton:
            self._send(protocol.back_or_screen_on(protocol.ACTION_DOWN))
            self._send(protocol.back_or_screen_on(protocol.ACTION_UP))
            return
        if button == Qt.MouseButton.MiddleButton:
            self._send(protocol.inject_keycode(protocol.ACTION_DOWN, keymap.KEYCODE_HOME))
            self._send(protocol.inject_keycode(protocol.ACTION_UP, keymap.KEYCODE_HOME))
            return
        if button != Qt.MouseButton.LeftButton:
            return
        pos = map_to_video(event.position().toPoint(), self.video_rect(), self._video)
        if pos is None:
            return
        self._pressed = True
        self._pinch = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self._last_video_pos = pos
        self._touch(protocol.ACTION_DOWN, protocol.POINTER_ID_GENERIC_FINGER, pos)
        if self._pinch:
            self._touch(protocol.ACTION_DOWN, protocol.POINTER_ID_VIRTUAL_FINGER, self._mirror(pos))

    def _clamped_video_pos(self, widget_pos: QPoint) -> QPoint:
        # ลากเลยขอบภาพไปแล้ว — ยึดนิ้วไว้ที่ขอบจอ ไม่ปล่อยกลางคัน (ปัดแถบแจ้งเตือนจากขอบบนได้)
        rect = self.video_rect()
        clamped = QPoint(min(max(widget_pos.x(), rect.left()), rect.right()),
                         min(max(widget_pos.y(), rect.top()), rect.bottom()))
        return map_to_video(clamped, rect, self._video) or self._last_video_pos

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._pressed:
            return
        pos = self._clamped_video_pos(event.position().toPoint())
        if pos == self._last_video_pos:
            return
        self._last_video_pos = pos
        self._touch(protocol.ACTION_MOVE, protocol.POINTER_ID_GENERIC_FINGER, pos)
        if self._pinch:
            self._touch(protocol.ACTION_MOVE, protocol.POINTER_ID_VIRTUAL_FINGER, self._mirror(pos))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            return
        self._last_video_pos = self._clamped_video_pos(event.position().toPoint())
        self._release_all()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._message:
            return
        pos = map_to_video(event.position().toPoint(), self.video_rect(), self._video)
        if pos is None:
            return
        delta = event.angleDelta()  # 120 = หนึ่งคลิกล้อ
        self._send(protocol.inject_scroll(pos.x(), pos.y(), self._video.width(), self._video.height(),
                                          hscroll=-delta.x() / 120, vscroll=delta.y() / 120))

    # ---- คีย์บอร์ด ----
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        mods = event.modifiers()
        if event.key() == Qt.Key.Key_V and mods & Qt.KeyboardModifier.ControlModifier:
            self.on_paste()
            return
        keycode = keymap.keycode_for(event.key(), mods)
        if keycode is not None:
            repeat = 1 if event.isAutoRepeat() else 0
            self._send(protocol.inject_keycode(protocol.ACTION_DOWN, keycode, repeat, keymap.meta_state(mods)))
            return
        text = event.text()
        if text and text.isprintable():
            self.on_key_text(text)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        keycode = keymap.keycode_for(event.key(), event.modifiers())
        if keycode is not None:
            self._send(protocol.inject_keycode(protocol.ACTION_UP, keycode, 0, keymap.meta_state(event.modifiers())))

    def focusNextPrevChild(self, _next: bool) -> bool:  # noqa: N802 — ให้ Tab ไปถึงมือถือ ไม่ใช่สลับ widget
        return False


class RemoteWindow(QMainWindow):
    closed = Signal(str)  # serial

    def __init__(self, adb: Adb, serial: str, settings: Settings, label: str = "") -> None:
        super().__init__()
        self.adb = adb
        self.serial = serial
        self.settings = settings
        self.label = label or serial
        self.options: StreamOptions = settings.stream_options
        self.session: Optional[ScrcpySession] = None
        self.receiver: Optional[VideoReceiver] = None
        self.control: Optional[ControlChannel] = None
        self._screen_off = False
        self._clipboard_seq = 1
        self._last_device_clipboard = ""
        self._sized_for: Optional[QSize] = None
        self._connecting = False
        self._closed = False

        self.setWindowTitle(f"Phone Remote — {self.label}")
        self.setStyleSheet(QSS)

        self.view = ScreenView(self._send)
        self.view.display_size_changed.connect(self._on_display_size)
        self.view.on_key_text = self._type_text
        self.view.on_paste = self._paste_pc_clipboard
        self.setCentralWidget(self.view)

        self._build_toolbar()
        self._build_statusbar()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._refresh_status)

        self._initial_resize(QSize(9, 19))
        self.connect_device()

    # ---- UI ----
    def _build_toolbar(self) -> None:
        tb = QToolBar("ปุ่มควบคุม", self)
        tb.setOrientation(Qt.Orientation.Vertical)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(22, 22))
        tb.setFixedWidth(TOOLBAR_WIDTH)
        self.addToolBar(Qt.ToolBarArea.RightToolBarArea, tb)

        def add(name: str, tip: str, handler: Callable[[], None], checkable: bool = False):
            act = tb.addAction(icons.icon(name), tip)
            act.setToolTip(tip)
            act.setCheckable(checkable)
            act.triggered.connect(lambda _checked=False: handler())
            self._actions[name] = act
            return act

        self._actions = {}
        add("back", "ย้อนกลับ (คลิกขวา / Esc)", self._press_back)
        add("home", "หน้าแรก (คลิกกลาง)", lambda: self._press_key(keymap.KEYCODE_HOME))
        add("recents", "สลับแอป", lambda: self._press_key(keymap.KEYCODE_APP_SWITCH))
        tb.addSeparator()
        add("vol_up", "เพิ่มเสียง", lambda: self._press_key(keymap.KEYCODE_VOLUME_UP))
        add("vol_down", "ลดเสียง", lambda: self._press_key(keymap.KEYCODE_VOLUME_DOWN))
        add("power", "ปุ่มเปิด/ปิดจอ (Power)", lambda: self._press_key(keymap.KEYCODE_POWER))
        tb.addSeparator()
        add("notifications", "เปิดแผงแจ้งเตือน", lambda: self._send(
            protocol.simple(protocol.TYPE_EXPAND_NOTIFICATION_PANEL)))
        add("rotate", "หมุนจอมือถือ", lambda: self._send(protocol.simple(protocol.TYPE_ROTATE_DEVICE)))
        add("screen_off", "ปิดจอมือถือ แต่ยังควบคุมจากคอมต่อได้", self._toggle_screen_off, checkable=True)
        tb.addSeparator()
        add("paste", "วางข้อความจากคอมลงมือถือ (Ctrl+V)", self._paste_pc_clipboard)
        add("screenshot", "แคปหน้าจอมือถือ (บันทึกเป็น PNG)", self._screenshot)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        spacer.setStyleSheet("background: transparent;")
        tb.addWidget(spacer)
        add("reconnect", "เชื่อมต่อใหม่", self.connect_device)

    def _build_statusbar(self) -> None:
        self._status = QLabel("")
        self.statusBar().addWidget(self._status, 1)
        self.statusBar().setSizeGripEnabled(True)

    def _initial_resize(self, video: QSize) -> None:
        """ให้หน้าต่างสูงราว 85% ของจอคอม และกว้างตามสัดส่วนจอมือถือ."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        chrome_h = 32 + 26  # แถบชื่อหน้าต่าง + แถบสถานะ (ประมาณ)
        box = QSize(int(avail.width() * 0.9) - TOOLBAR_WIDTH, int(avail.height() * 0.85) - chrome_h)
        r = fit_rect(box, video)
        self.resize(r.width() + TOOLBAR_WIDTH, r.height() + 26)

    # ---- เชื่อมต่อ ----
    def connect_device(self) -> None:
        if self._connecting:
            return
        self._connecting = True
        self._teardown()
        self._actions["reconnect"].setEnabled(False)
        self.view.set_message(f"กำลังเชื่อมต่อ {self.label} ...")
        self._set_status("กำลังเชื่อมต่อ ...")
        session = ScrcpySession(self.adb, self.serial, self.options)
        run_async(lambda: session.start(), self._on_connected, self._on_connect_error, self)

    def _on_connected(self, session: ScrcpySession) -> None:
        self._connecting = False
        self._actions["reconnect"].setEnabled(True)
        if self._closed:  # ผู้ใช้ปิดหน้าต่างไประหว่างรอ
            session.close()
            return
        self.session = session
        self.setWindowTitle(f"Phone Remote — {session.device_name or self.label}")
        self.control = ControlChannel(session.control_sock, self)
        self.control.clipboard_received.connect(self._on_device_clipboard)
        self.control.failed.connect(self._on_stream_stopped)
        self.control.start()
        self.receiver = VideoReceiver(session.video_sock, self)
        self.receiver.session_changed.connect(self._on_video_session)
        self.receiver.frame_ready.connect(self._on_frame_ready)
        self.receiver.stopped.connect(self._on_stream_stopped)
        self.receiver.start()
        self.view.set_message("รอภาพแรกจากมือถือ ...")
        self._stats_timer.start()
        self._refresh_status()

    def _on_connect_error(self, message: str) -> None:
        self._connecting = False
        self._actions["reconnect"].setEnabled(True)
        self.view.set_message(f"เชื่อมต่อไม่สำเร็จ\n\n{message}\n\nกดปุ่ม ⟳ ด้านขวาล่างเพื่อลองใหม่")
        self._set_status("เชื่อมต่อไม่สำเร็จ")

    def _on_video_session(self, width: int, height: int) -> None:
        self.view.set_video_size(width, height)
        if self.receiver is not None:
            r = self.view.video_rect()
            ratio = self.view.devicePixelRatioF()
            self.receiver.set_target_size(round(r.width() * ratio), round(r.height() * ratio))
        size = QSize(width, height)
        orientation_changed = self._sized_for is None or (
            (self._sized_for.width() > self._sized_for.height()) != (width > height))
        if orientation_changed and not (self.isMaximized() or self.isFullScreen()):
            self._initial_resize(size)
        self._sized_for = size

    def _on_display_size(self, width: int, height: int) -> None:
        if self.receiver is not None:
            self.receiver.set_target_size(width, height)

    def _on_frame_ready(self) -> None:
        if self.receiver is None:
            return
        image = self.receiver.take_frame()
        if image is not None:
            self.view.set_image(image)

    def _on_stream_stopped(self, reason: str) -> None:
        if not reason:
            return
        self._teardown()
        self.view.set_message(f"{reason}\n\nกดปุ่ม ⟳ ด้านขวาล่างเพื่อเชื่อมต่อใหม่")
        self._set_status("หลุดการเชื่อมต่อ")

    def _teardown(self) -> None:
        self._stats_timer.stop()
        receiver, control, session = self.receiver, self.control, self.session
        self.receiver = self.control = self.session = None
        if receiver is not None:
            receiver.stop()
        if control is not None:
            control.stop()
        if session is not None:
            session.close()  # ปิด socket -> thread ที่รอ recv() อยู่หลุดออกเอง
        if receiver is not None:
            receiver.wait(3000)
            receiver.deleteLater()
        if control is not None:
            control.deleteLater()

    # ---- คำสั่ง ----
    def _send(self, message: bytes) -> bool:
        return self.control.send(message) if self.control is not None else False

    def _press_key(self, keycode: int) -> None:
        self._send(protocol.inject_keycode(protocol.ACTION_DOWN, keycode))
        self._send(protocol.inject_keycode(protocol.ACTION_UP, keycode))

    def _press_back(self) -> None:
        self._send(protocol.back_or_screen_on(protocol.ACTION_DOWN))
        self._send(protocol.back_or_screen_on(protocol.ACTION_UP))

    def _type_text(self, text: str) -> None:
        if keymap.is_injectable_text(text):
            self._send(protocol.inject_text(text))
        else:  # ภาษาไทย/อีโมจิ — วางผ่าน clipboard ของมือถือ
            self._set_device_clipboard(text, paste=True)

    def _set_device_clipboard(self, text: str, paste: bool) -> None:
        self._clipboard_seq += 1
        self._last_device_clipboard = text  # กันไม่ให้ข้อความนี้เด้งกลับมาทับ clipboard คอม
        self._send(protocol.set_clipboard(self._clipboard_seq, text, paste))

    def _paste_pc_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self._set_device_clipboard(text, paste=True)
            self._flash(f"วางข้อความ {len(text)} ตัวอักษรลงมือถือแล้ว")

    def _on_device_clipboard(self, text: str) -> None:
        # คัดลอกบนมือถือ -> ไปอยู่ใน clipboard ของคอมด้วย (Ctrl+V บนคอมได้เลย)
        if text and text != self._last_device_clipboard:
            self._last_device_clipboard = text
            QGuiApplication.clipboard().setText(text)
            self._flash("คัดลอกข้อความจากมือถือมาที่คอมแล้ว")

    def _toggle_screen_off(self) -> None:
        self._screen_off = not self._screen_off
        self._actions["screen_off"].setChecked(self._screen_off)
        self._send(protocol.set_display_power(not self._screen_off))
        self._flash("ปิดจอมือถือแล้ว (คอมยังเห็นภาพ)" if self._screen_off else "เปิดจอมือถือแล้ว")

    def _screenshot(self) -> None:
        image = self.receiver.full_resolution_image() if self.receiver is not None else None
        if image is None:
            self._flash("ยังไม่มีภาพให้แคป")
            return
        folder = self.settings.resolved_screenshot_dir
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, datetime.datetime.now().strftime("phone_%Y%m%d_%H%M%S.png"))
        if image.save(path, "PNG"):
            self._flash(f"บันทึกแล้ว: {path}")
        else:
            self._flash("บันทึกภาพไม่สำเร็จ")

    # ---- สถานะ ----
    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _flash(self, text: str) -> None:
        self.statusBar().showMessage(text, 4000)

    def _refresh_status(self) -> None:
        if self.session is None:
            return
        video = self.view.video_size
        fps = self.receiver.fps if self.receiver is not None else 0.0
        size = f"{video.width()}×{video.height()}" if video.width() else "—"
        self._set_status(f"● {self.session.device_name or self.label}   ·   {size}   ·   {fps:.0f} fps"
                         f"   ·   {self.serial}")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closed = True
        if self._screen_off:  # อย่าทิ้งจอมือถือดับค้างไว้ตอนเลิกใช้
            self._send(protocol.set_display_power(True))
        self._teardown()
        self.closed.emit(self.serial)
        super().closeEvent(event)
