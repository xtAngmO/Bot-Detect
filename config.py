"""Settings model for Number Sequence Bot — load/save JSON next to the script.

ห้ามให้สคริปต์ทดสอบเขียนทับ config.json ของผู้ใช้จริง (บทเรียนจากโปรเจกต์พี่น้อง
bot_detect_word ที่เคยโดนมาโครหายทั้งไฟล์) — ทดสอบให้ patch Settings.save เป็น no-op
หรือชี้ CONFIG_PATH ไปโฟลเดอร์ชั่วคราวก่อน import โมดูลอื่น
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

Rect = Tuple[int, int, int, int]  # (left, top, width, height) — absolute screen px

# โหมดการเล่น (ผู้ใช้เลือกในหน้าต่างหลัก)
MODE_OCR = "ocr"  # 2 กรอบ: ตาราง + เลขต่อไป — ยืนยันทุกคลิกจากกรอบเลขต่อไป แตะไม่ติดก็ resync เอง
MODE_GRID = "grid"  # กรอบตารางอย่างเดียว: อ่านครั้งเดียวแล้วกดเรียงต่อเนื่องจนครบ ไม่รอยืนยันจากเกม


@dataclass
class Settings:
    grid_box: Optional[Rect] = None
    next_box: Optional[Rect] = None  # ไม่ใช้ในโหมด MODE_GRID
    mode: str = MODE_OCR
    rows: int = 5
    cols: int = 5
    max_number: int = 25
    click_delay_ms: int = 150
    poll_interval_ms: int = 300
    # เวลาจากคลิกแรกถึงคลิกสุดท้ายของทั้งเกม (1..max_number) — 0 = เร็วสุด ไม่เว้นจังหวะ
    target_total_s: int = 0
    max_consecutive_miss: int = 20
    panic_key: str = "esc"
    tesseract_cmd: str = ""  # ว่าง = ให้ pytesseract หาเอง/ใช้ path เริ่มต้นของ capture.py

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Settings":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        s = cls(**known)
        # dataclass เก็บ tuple แต่ json คืน list — แปลงกลับ
        if s.grid_box is not None:
            s.grid_box = tuple(s.grid_box)  # type: ignore[assignment]
        if s.next_box is not None:
            s.next_box = tuple(s.next_box)  # type: ignore[assignment]
        return s

    @classmethod
    def load(cls, path: str = CONFIG_PATH) -> "Settings":
        if not os.path.isfile(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_json(data)
        except Exception:
            return cls()

    def save(self, path: str = CONFIG_PATH) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
