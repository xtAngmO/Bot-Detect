"""ไอคอนลายเส้นของแถบปุ่มด้านข้าง — วาดด้วย QPainter บนตาราง 24×24 (ไม่พึ่งไฟล์รูป/ฟอนต์อีโมจิ
ที่แต่ละเครื่อง Windows แสดงไม่เหมือนกัน) วาดที่ 3 เท่าแล้วให้ Qt ย่อ เพื่อให้คมบนจอ DPI สูง."""
from __future__ import annotations

from typing import Callable, Dict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

_SCALE = 3


def _poly(*pts: float) -> QPolygonF:
    return QPolygonF([QPointF(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)])


def _back(p: QPainter) -> None:
    p.drawPolygon(_poly(16, 5, 16, 19, 6.5, 12))


def _home(p: QPainter) -> None:
    p.drawEllipse(QPointF(12, 12), 7, 7)


def _recents(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(5.5, 5.5, 13, 13), 2, 2)


def _speaker(p: QPainter) -> None:
    p.drawPolygon(_poly(3.5, 9.5, 7, 9.5, 11.5, 5.5, 11.5, 18.5, 7, 14.5, 3.5, 14.5))


def _vol_up(p: QPainter) -> None:
    _speaker(p)
    p.drawLine(QPointF(15, 12), QPointF(21, 12))
    p.drawLine(QPointF(18, 9), QPointF(18, 15))


def _vol_down(p: QPainter) -> None:
    _speaker(p)
    p.drawLine(QPointF(15, 12), QPointF(21, 12))


def _power(p: QPainter) -> None:
    p.drawArc(QRectF(5, 5.5, 14, 14), 125 * 16, -250 * 16)
    p.drawLine(QPointF(12, 3.5), QPointF(12, 11))


def _rotate(p: QPainter) -> None:
    p.drawArc(QRectF(5, 5, 14, 14), 100 * 16, -290 * 16)
    p.drawPolyline(_poly(4.5, 5.5, 8.6, 5.4, 8.2, 9.5))


def _notifications(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(4, 4, 16, 5), 1.5, 1.5)
    p.drawPolyline(_poly(8, 13.5, 12, 17.5, 16, 13.5))


def _screen_off(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(7, 3.5, 10, 17), 2, 2)
    p.drawLine(QPointF(4, 4), QPointF(20, 20))


def _paste(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(5.5, 5, 13, 15.5), 2, 2)
    p.drawRoundedRect(QRectF(9, 3, 6, 4), 1, 1)
    p.drawLine(QPointF(9, 12), QPointF(15, 12))
    p.drawLine(QPointF(9, 15.5), QPointF(13, 15.5))


def _screenshot(p: QPainter) -> None:
    body = QPainterPath()
    body.moveTo(3.5, 8.5)
    body.lineTo(8, 8.5)
    body.lineTo(9.5, 6)
    body.lineTo(14.5, 6)
    body.lineTo(16, 8.5)
    body.lineTo(20.5, 8.5)
    body.lineTo(20.5, 18.5)
    body.lineTo(3.5, 18.5)
    body.closeSubpath()
    p.drawPath(body)
    p.drawEllipse(QPointF(12, 13.2), 3, 3)


def _reconnect(p: QPainter) -> None:
    p.drawArc(QRectF(5, 5, 14, 14), 30 * 16, 150 * 16)
    p.drawArc(QRectF(5, 5, 14, 14), 210 * 16, 150 * 16)
    p.drawPolyline(_poly(15.5, 4, 17.3, 6.5, 14.4, 7.6))
    p.drawPolyline(_poly(8.5, 20, 6.7, 17.5, 9.6, 16.4))


_DRAW: Dict[str, Callable[[QPainter], None]] = {
    "back": _back, "home": _home, "recents": _recents,
    "vol_up": _vol_up, "vol_down": _vol_down, "power": _power,
    "rotate": _rotate, "notifications": _notifications, "screen_off": _screen_off,
    "paste": _paste, "screenshot": _screenshot, "reconnect": _reconnect,
}

NAMES = tuple(_DRAW)


def icon(name: str, color: str = "#ededed", disabled_color: str = "#4a4a4d") -> QIcon:
    result = QIcon()
    for mode, c in ((QIcon.Mode.Normal, color), (QIcon.Mode.Disabled, disabled_color)):
        pm = QPixmap(24 * _SCALE, 24 * _SCALE)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(_SCALE, _SCALE)
        pen = QPen(QColor(c), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        _DRAW[name](p)
        p.end()
        result.addPixmap(pm, mode)
    return result
