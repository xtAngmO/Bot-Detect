"""กรอบโปร่งใสลาก/ย่อ-ขยายได้ + วงไฮไลต์กะพริบชี้เป้า

เทคนิคคลิกทะลุกลางกรอบ: ใช้ setMask(บริเวณทั้งหมด - รูตรงกลาง) **ห้ามใช้
Qt.WindowTransparentForInput** เพราะจะทำให้คลิกทะลุทั้งบานจนลากขอบ/ย่อขยายไม่ได้เลย
(บทเรียนจากโปรเจกต์พี่น้อง bot_detect_word/ui_overlay.py) — setMask ทำให้เฉพาะเส้นขอบหนา
รับคลิก (ลาก/ย่อขยายได้) ส่วนพื้นที่ตรงกลางไม่อยู่ใน region เลยคลิกทะลุไปโดนแอปข้างล่างแทน

กรอบตารางตีเส้น grid ตามแถว×คอลัมน์ (`set_grid`) ให้เล็งเส้นตรงรอยต่อการ์ดได้ — เส้นต้องอยู่ใน mask ด้วย
(นอก mask วาดไม่ติด) หนาแค่ 1px ตรงรอยต่อช่อง: จุดคลิกของบอทคือกลางช่อง และ OCR ตัดขอบช่องทิ้ง 16% ก่อนอ่าน
(`cell_pad_ratio`) เส้นที่ mss จับติดมาด้วยจึงไม่กวนทั้งการคลิกและการอ่าน
"""
from __future__ import annotations

import sys
from typing import Optional, Tuple

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

Rect = Tuple[int, int, int, int]

_BORDER = 6
_HANDLE = 16
_GRID_LINE = 1


def _keep_visible_when_inactive(widget: QWidget) -> None:
    """macOS: กันกรอบ/วงไฮไลต์หายตอนสลับไปหน้าต่างอื่น

    Qt.Tool บน macOS กลายเป็น NSPanel ที่ตั้ง hidesOnDeactivate ไว้ = ซ่อนตัวเองทันทีที่แอปเราไม่ได้อยู่หน้า
    ผลคือพอผู้ใช้คลิกหน้าต่างเกม (scrcpy/เบราว์เซอร์) เพื่อเล็งกรอบ กรอบเขียวก็หายไปเลย ลากทาบไม่ได้
    และวงไฮไลต์ตอนบอททำงานก็ไม่โผล่ — ปลด flag นั้นทิ้งซะ (ฝั่ง Windows ไม่มีปัญหานี้)
    ต้องเรียกตอน showEvent เพราะกว่า NSWindow จริงจะถูกสร้างก็คือตอนแสดงผลครั้งแรก
    """
    if sys.platform != "darwin":
        return
    # ต้องเช็คว่าเป็น platform cocoa จริงๆ ก่อน — ตอนเทสต์ใช้ QT_QPA_PLATFORM=offscreen ซึ่ง winId()
    # ไม่ใช่ NSView จริง ส่งเข้า objc แล้ว **segfault ทั้งโปรเซส** (try/except ดักไม่ได้ ต้องกันไว้ก่อน)
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "cocoa":
        return
    handle = int(widget.winId())
    if not handle:
        return
    try:
        import objc

        window = objc.objc_object(c_void_p=handle).window()
        if window is not None:
            window.setHidesOnDeactivate_(False)
    except Exception:
        pass  # ไม่ได้ก็แค่กลับไปเป็นพฤติกรรมเดิม ไม่ควรทำให้กรอบเปิดไม่ขึ้น


class FrameOverlay(QWidget):
    """กรอบที่ลาก (แถบขอบ) และย่อ-ขยายได้ (มุมขวาล่าง) พื้นที่ตรงกลางคลิกทะลุ."""

    def __init__(self, label: str, color: str = "#22c55e", on_change=None) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._label = label
        self._color = QColor(color)
        self._drag_offset = None
        self._resizing = False
        self._on_change = on_change
        self._grid: Optional[Tuple[int, int]] = None  # (rows, cols) — None = ไม่ตีเส้น
        self.setMinimumSize(80, 80)
        self.resize(380, 380)
        self.move(200, 200)
        self._apply_mask()

    # ---- geometry / mask -------------------------------------------------
    def set_grid(self, rows: int, cols: int) -> None:
        """ตีเส้นแบ่งช่องในกรอบ — แบ่งแบบเดียวกับที่บอทหารกรอบเป็นช่อง (capture.cell_center)."""
        self._grid = (rows, cols) if rows > 0 and cols > 0 else None
        self._apply_mask()
        self.update()

    def _grid_lines(self) -> list:
        if not self._grid:
            return []
        rows, cols = self._grid
        inner = self.rect().adjusted(_BORDER, _BORDER, -_BORDER, -_BORDER)
        lines = [QRect(inner.left() + round(inner.width() * c / cols), inner.top(), _GRID_LINE, inner.height())
                 for c in range(1, cols)]
        lines += [QRect(inner.left(), inner.top() + round(inner.height() * r / rows), inner.width(), _GRID_LINE)
                  for r in range(1, rows)]
        return lines

    def _apply_mask(self) -> None:
        outer = QRegion(self.rect())
        inner = QRegion(self.rect().adjusted(_BORDER, _BORDER, -_BORDER, -_BORDER))
        region = outer.subtracted(inner)
        for line in self._grid_lines():
            region = region.united(QRegion(line))
        self.setMask(region)

    def _notify_change(self) -> None:
        if self._on_change:
            self._on_change(self.rect_on_screen())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        _keep_visible_when_inactive(self)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._apply_mask()
        super().resizeEvent(event)
        self._notify_change()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._notify_change()

    def rect_on_screen(self) -> Rect:
        g = self.geometry()
        return (
            g.x() + _BORDER,
            g.y() + _BORDER,
            g.width() - 2 * _BORDER,
            g.height() - 2 * _BORDER,
        )

    # ---- paint -------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color, _BORDER)
        p.setPen(pen)
        half = _BORDER / 2
        p.drawRect(self.rect().adjusted(int(half), int(half), -int(half), -int(half)))
        line_color = QColor(self._color)
        line_color.setAlpha(170)
        for line in self._grid_lines():
            p.fillRect(line, line_color)
        p.setPen(QColor("#fafafa"))
        p.drawText(_BORDER + 4, _BORDER + 14, self._label)
        p.fillRect(
            self.width() - _HANDLE, self.height() - _HANDLE, _HANDLE, _HANDLE, QColor("#3b82f6")
        )

    # ---- drag / resize -------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        handle_rect = QRect(self.width() - _HANDLE, self.height() - _HANDLE, _HANDLE, _HANDLE)
        if handle_rect.contains(pos):
            self._resizing = True
        else:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._resizing:
            pos = event.position().toPoint()
            new_w = max(self.minimumWidth(), pos.x())
            new_h = max(self.minimumHeight(), pos.y())
            self.resize(new_w, new_h)
        elif self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._resizing = False
        self._drag_offset = None
        self._notify_change()


class HighlightRing(QWidget):
    """วงไฮไลต์กะพริบชี้เป้าตัวเลขที่กำลังจะกด — ไม่รับคลิกเลย (มองทะลุ 100%) โชว์ชั่วครู่แล้วซ่อนเอง."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        _keep_visible_when_inactive(self)

    def flash_at(self, rect: Rect, duration_ms: int = 450) -> None:
        x, y, w, h = rect
        pad = 8
        self.setGeometry(x - pad, y - pad, w + 2 * pad, h + 2 * pad)
        self.show()
        self.raise_()
        self._timer.start(duration_ms)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#22c55e"), 5)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 10, 10)
