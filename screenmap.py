"""แปลงพิกัด Qt (logical px) <-> พิกัดจอจริง (physical px)

Qt 6 ทำงานเป็น logical px เสมอ (กรอบ overlay, config.json เก็บค่านี้) แต่ mss (จับภาพ) และ
SendInput (คลิก) ใช้ physical px — บนจอที่ตั้ง scale ไว้ 125% กรอบที่ผู้ใช้เห็นอยู่ที่ logical × 1.25
ถ้าส่งพิกัด Qt ไปจับภาพตรงๆ จะได้ภาพผิดที่ทั้งก้อน (เคยพัง: บอทขึ้น "อ่านเลขต่อไปไม่ออก" รัวๆ
เพราะไปจับเมนูของหน้าต่างอื่นแทนตัวเลขในเกม)

สูตรของ Qt: จุดมุมซ้ายบนของแต่ละจอเท่ากันทั้งสองระบบ ส่วนที่เหลือคูณ devicePixelRatio ของจอนั้น
    physical = origin + (logical - origin) * scale
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class ScreenMap:
    origin_x: int = 0
    origin_y: int = 0
    scale: float = 1.0

    @classmethod
    def for_rect(cls, rect: Rect) -> "ScreenMap":
        """หาจอที่กลางกรอบ (logical) อยู่ แล้วเก็บ origin/scale ของจอนั้นไว้ — ต้องเรียกบน GUI thread
        (ใช้ QGuiApplication) ผลลัพธ์เป็นค่าคงที่ธรรมดา ส่งต่อให้ thread อื่นใช้ได้เลย."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication

        x, y, w, h = rect
        screen = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2))
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return cls()
        g = screen.geometry()
        return cls(g.x(), g.y(), screen.devicePixelRatio())

    def to_physical(self, rect: Rect) -> Rect:
        x, y, w, h = rect
        left = self.origin_x + round((x - self.origin_x) * self.scale)
        top = self.origin_y + round((y - self.origin_y) * self.scale)
        # ปัดขอบขวา/ล่างแยก แทนการปัด w/h ตรงๆ — กันขอบเพี้ยนสะสมทีละ 1px
        right = self.origin_x + round((x + w - self.origin_x) * self.scale)
        bottom = self.origin_y + round((y + h - self.origin_y) * self.scale)
        return (left, top, right - left, bottom - top)

    def point_to_logical(self, x: int, y: int) -> Tuple[int, int]:
        return (
            self.origin_x + round((x - self.origin_x) / self.scale),
            self.origin_y + round((y - self.origin_y) / self.scale),
        )
