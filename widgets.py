"""วิดเจ็ตชุดเล็กตามแบบ bot_detect_word (ui_widgets.py) — เซ็กชัน, บรรทัดสถานะจุดเต้น, segmented, ตัวเลขใหญ่"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtCore import QEasingCurve, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import theme
from theme import PALETTE, SP


def hline(kind: str = "hair") -> QFrame:
    line = QFrame()
    line.setObjectName(kind)
    line.setFixedHeight(1)
    return line


def repolish(w: QWidget) -> None:
    """property เปลี่ยนแล้ว QSS ไม่คำนวณใหม่เอง — ต้องสั่ง."""
    w.style().unpolish(w)
    w.style().polish(w)


def button(text: str, icon: str = "", kind: str = "", run: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("btn")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if run:
        btn.setProperty("size", "run")
    set_button(btn, kind, icon)
    return btn


def set_button(btn: QPushButton, kind: str = "", icon: str = "", text: Optional[str] = None) -> None:
    """เปลี่ยนชนิด (primary/stop/ghost) + ไอคอน — สีไอคอนตามตัวอักษรของชนิดนั้น."""
    if text is not None:
        btn.setText(text)
    btn.setProperty("kind", kind)
    color = PALETTE["on-white"] if kind == "primary" else PALETTE["text"]
    btn.setIcon(theme.icon(icon, color, 16) if icon else QIcon())
    btn.setIconSize(QSize(16, 16))
    repolish(btn)


class Section(QWidget):
    """`.sec` ของ bot_detect_word: เส้นคั่นบน 1px, padding 16/20, หัวข้อ 18px + meta ชิดขวา."""

    def __init__(self, title: str, meta: str = "", kbd: str = "") -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(hline("rule"))
        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(SP(5), SP(4), SP(5), SP(5))
        self.body.setSpacing(SP(2))
        outer.addWidget(inner)

        head = QHBoxLayout()
        head.setSpacing(SP(2))
        self.title = QLabel(title)
        self.title.setObjectName("secTitle")
        self.title.setFont(theme.sans_font(theme.T_TITLE, QFont.Weight.DemiBold))
        head.addWidget(self.title, 1)
        self.meta = QLabel(meta)
        self.meta.setObjectName("meta")
        self.meta.setFont(theme.mono_font(theme.T_MICRO, mix=True))
        self.meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.meta)
        if kbd:
            k = QLabel(kbd)
            k.setObjectName("kbd")
            k.setFont(theme.mono_font(theme.T_MICRO))
            head.addWidget(k)
        self.body.addLayout(head)


class StatDot(QWidget):
    """บรรทัดสถานะใหญ่ (T_LEAD) + จุดสี — จุด "เต้น" ตอนกำลังทำงาน ให้เห็นทันทีว่าบอทยังวิ่งอยู่.

    state: idle | starting | running | done | stopped | error."""

    _ICON = {"idle": "circle", "starting": "circle", "running": "circle", "done": "check",
             "stopped": "square", "error": "x"}

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._state = "idle"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP(2))
        self._dot = QLabel()
        self._dot.setFixedSize(18, 18)
        lay.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._text = QLabel(text)
        self._text.setFont(theme.sans_font(theme.T_LEAD, QFont.Weight.DemiBold))
        lay.addWidget(self._text, 1, Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._fx = QGraphicsOpacityEffect(self._dot)
        self._fx.setOpacity(1.0)
        self._dot.setGraphicsEffect(self._fx)
        self._pulse = QVariantAnimation(self)
        self._pulse.setDuration(800)
        self._pulse.setStartValue(0.3)
        self._pulse.setKeyValueAt(0.5, 1.0)
        self._pulse.setEndValue(0.3)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(lambda v: self._fx.setOpacity(float(v)))
        self.set_state("idle", text)

    def state(self) -> str:
        return self._state

    def text(self) -> str:
        return self._text.text()

    def set_state(self, state: str, text: str) -> None:
        self._state = state
        self._text.setText(text)
        color = {
            "idle": PALETTE["text-faint"], "starting": PALETTE["amber"], "running": PALETTE["green"],
            "done": PALETTE["green"], "stopped": PALETTE["text-dim"], "error": PALETTE["log-err"],
        }.get(state, PALETTE["text-faint"])
        text_color = PALETTE["white"] if state in ("running", "done") else (
            PALETTE["log-err"] if state == "error" else PALETTE["text-dim"])
        self._text.setStyleSheet(f"color: {text_color};")
        if state in ("running", "starting"):  # จุดทึบ (เต้น) แทนไอคอนเส้น
            dpr = self.devicePixelRatioF()
            pm = QPixmap(int(18 * dpr), int(18 * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(3, 3, 12, 12)
            p.end()
        else:
            pm = theme.pixmap(self._ICON.get(state, "circle"), color, 18, stroke=2.0)
        self._dot.setPixmap(pm)
        if state in ("running", "starting"):
            if self._pulse.state() != QVariantAnimation.State.Running:
                self._pulse.start()
        else:
            self._pulse.stop()
            self._fx.setOpacity(1.0)


class Segmented(QFrame):
    """ปุ่มเลือกทีละอัน (segmented control) — changed(data)."""

    changed = Signal(object)

    def __init__(self, options: Sequence[Tuple[str, object, str]]) -> None:
        super().__init__()
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._buttons: list[tuple[QPushButton, object, str]] = []
        for label, data, icon_name in options:
            b = QPushButton(label)
            b.setObjectName("segBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(28)
            b.clicked.connect(lambda _=False, d=data: self.set_value(d, emit=True))
            lay.addWidget(b, 1)
            self._buttons.append((b, data, icon_name))
        self._value = options[0][1] if options else None
        self._paint()

    def value(self):
        return self._value

    def set_value(self, data, emit: bool = False) -> None:
        changed = data != self._value
        self._value = data
        self._paint()
        if emit and changed:
            self.changed.emit(data)

    def setEnabled(self, on: bool) -> None:  # noqa: N802 (Qt API)
        super().setEnabled(on)
        self._paint()

    def _paint(self) -> None:
        for b, data, icon_name in self._buttons:
            on = data == self._value
            b.setProperty("on", "1" if on else "0")
            if icon_name:
                b.setIcon(theme.icon(icon_name, PALETTE["white"] if on else PALETTE["text-faint"], 16))
            repolish(b)


class Stat(QWidget):
    """ตัวเลขใหญ่ (mono) + ป้ายเล็กด้านบน — แบบช่อง X/Y/กว้าง/สูง ของ bot_detect_word."""

    def __init__(self, label: str, value: str = "—") -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP(1))
        cap = QLabel(label)
        cap.setObjectName("fieldLabel")
        lay.addWidget(cap)
        self.value = QLabel(value)
        self.value.setFont(theme.mono_font(theme.T_DISPLAY))
        self.value.setStyleSheet(f"color: {PALETTE['white']};")
        lay.addWidget(self.value)

    def set(self, text: str) -> None:
        self.value.setText(text)

    def text(self) -> str:
        return self.value.text()


def setting_row(label: str, *controls: QWidget, note: str = "") -> QWidget:
    """แถว "ป้ายซ้าย — ช่องกรอกขวา" มีเส้นบางคั่นใต้แถว (แบบคอลัมน์ OCR ของ bot_detect_word)."""
    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    row = QHBoxLayout()
    row.setContentsMargins(0, SP(1), 0, SP(1))
    row.setSpacing(SP(2))
    key = QLabel(label)
    key.setObjectName("rowKey")
    row.addWidget(key, 1)
    for c in controls:
        row.addWidget(c)
    outer.addLayout(row)
    if note:
        n = QLabel(note)
        n.setObjectName("note")
        n.setWordWrap(True)
        outer.addWidget(n)
    outer.addWidget(hline("hair"))
    return w
