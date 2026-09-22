"""ค่าที่จำไว้ข้ามการเปิดโปรแกรม — phone_remote/config.json (อยู่ใน .gitignore แล้ว).

เทสต์ห้ามเขียนทับ config.json ของผู้ใช้จริง: patch Settings.save เป็น no-op ก่อนสร้างหน้าต่างใด ๆ
(กติกาเดียวกับ config.py ของบอทเรียงเลข)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, Tuple

from scrcpy_server import StreamOptions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ข้ามอินเทอร์เน็ต ภาพหน่วงเพราะ bitrate เกินความเร็วเน็ตขาอัปของฝั่งมือถือเป็นหลัก — เลือกให้เหมาะกับเน็ต
QUALITY_PRESETS: Dict[str, Tuple[str, StreamOptions]] = {
    "eco": ("ประหยัดเน็ต — 720p · 1.5 Mbps · 24 fps (เน็ตมือถือ/สัญญาณอ่อน)",
            StreamOptions(max_size=720, bit_rate=1_500_000, max_fps=24)),
    "balanced": ("สมดุล — 1024p · 3 Mbps · 30 fps (แนะนำเมื่อต่อข้ามเน็ต)",
                 StreamOptions(max_size=1024, bit_rate=3_000_000, max_fps=30)),
    "sharp": ("คมชัด — 1600p · 8 Mbps · 60 fps (USB หรือเน็ตแรงทั้งสองฝั่ง)",
              StreamOptions(max_size=1600, bit_rate=8_000_000, max_fps=60)),
}
DEFAULT_QUALITY = "balanced"


@dataclass
class Settings:
    adb_path: str = ""  # ว่าง = หาเอง (PATH / Android SDK)
    host: str = ""  # IP ของมือถือ (Tailscale 100.x.y.z หรือ IP ในวง Wi-Fi)
    connect_port: str = ""  # พอร์ตในหน้า Wireless debugging ("IP address & Port") — เปลี่ยนทุกครั้งที่เปิดใหม่
    quality: str = DEFAULT_QUALITY
    screenshot_dir: str = ""  # ว่าง = Pictures/PhoneRemote

    @property
    def stream_options(self) -> StreamOptions:
        return QUALITY_PRESETS.get(self.quality, QUALITY_PRESETS[DEFAULT_QUALITY])[1]

    @property
    def resolved_screenshot_dir(self) -> str:
        return self.screenshot_dir or os.path.join(os.path.expanduser("~"), "Pictures", "PhoneRemote")

    @classmethod
    def load(cls, path: str = CONFIG_PATH) -> "Settings":
        if not os.path.isfile(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
        except Exception:
            return cls()

    def save(self, path: str = CONFIG_PATH) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
