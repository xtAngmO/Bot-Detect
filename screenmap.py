"""แปลงพิกัด Qt (logical px) <-> พิกัดที่ใช้จับภาพ/คลิกจริง

**Windows**: Qt 6 ทำงานเป็น logical px เสมอ (กรอบ overlay, config.json เก็บค่านี้) แต่ mss (จับภาพ) และ
SendInput (คลิก) ใช้ physical px — บนจอที่ตั้ง scale ไว้ 125% กรอบที่ผู้ใช้เห็นอยู่ที่ logical × 1.25
ถ้าส่งพิกัด Qt ไปจับภาพตรงๆ จะได้ภาพผิดที่ทั้งก้อน (เคยพัง: บอทขึ้น "อ่านเลขต่อไปไม่ออก" รัวๆ
เพราะไปจับเมนูของหน้าต่างอื่นแทนตัวเลขในเกม)

สูตรของ Qt: จุดมุมซ้ายบนของแต่ละจอเท่ากันทั้งสองระบบ ส่วนที่เหลือคูณ devicePixelRatio ของจอนั้น
    physical = origin + (logical - origin) * scale

**macOS**: ไม่ต้องแปลงเลย (scale = 1) — ทั้ง mss และ CGEvent ใช้ "points" ชุดเดียวกับ Qt ไม่ใช่พิกเซลจริง
บนจอ Retina ที่ dpr = 2 (วัดจริง: จอ 1512×982 points = 3024×1964 px, mss.grab ขอ 200×150 ได้ภาพ 200×150)
ถ้าเผลอคูณ dpr ตาม Qt เหมือนฝั่ง Windows จะจับภาพและคลิกเลยไปเท่าตัว — หลุดจอไปเลยด้วยซ้ำ
ภาพที่ mss คืนมาบน Retina จึงละเอียดกว่าที่ขอ 2 เท่าโดยอัตโนมัติ ซึ่งเป็นผลดีกับ OCR (capture.py
ปรับขนาดตามความสูงตัวเลขที่วัดได้อยู่แล้ว ไม่ยึดขนาดที่ขอ)
"""
from __future__ import annotations

import sys
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
        if sys.platform == "darwin":
            return cls(g.x(), g.y(), 1.0)  # mss/CGEvent ใช้ points เดียวกับ Qt — ดูหัวไฟล์
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
