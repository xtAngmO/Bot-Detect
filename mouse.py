"""คลิกที่พิกัดจอสัมบูรณ์ — เลือก backend ตามระบบปฏิบัติการ

ทั้งสองระบบใช้ท่าหลักเดียวกัน: จุดที่อยู่บนหน้าต่าง scrcpy จะ **แตะตรงเข้ามือถือ** ผ่าน `phonetap`
(scrcpy-server ตัวที่สอง) โดยไม่ขยับเมาส์จริงเลย ต่างกันแค่วิธีหาหน้าต่างและทางสำรองเมื่อต่อมือถือไม่ได้:

- `mouse_win` (Windows) — หาหน้าต่างด้วย EnumWindows/class name, สำรองด้วย PostMessage, อย่างอื่นใช้ SendInput
- `mouse_mac` (macOS)   — หาหน้าต่างด้วย CGWindowList, อย่างอื่น (และทางสำรอง) ใช้ CGEvent

หน้าตาที่ผู้เรียกใช้เหมือนกันทั้งคู่: prepare() / click() / move() ดูรายละเอียดในไฟล์ backend
"""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from mouse_mac import click, close_phones, move, prepare
elif sys.platform == "win32":
    from mouse_win import click, close_phones, move, prepare
else:
    raise ImportError(f"ยังไม่รองรับระบบปฏิบัติการ {sys.platform!r} (รองรับ Windows กับ macOS)")

__all__ = ["click", "close_phones", "move", "prepare"]
