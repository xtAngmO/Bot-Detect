"""ที่อยู่ของไฟล์ประกอบและไฟล์ตั้งค่า — คนละที่กันระหว่างรันจากซอร์สกับรันจากไฟล์ที่แพ็กแล้ว

รันจากซอร์ส: ทุกอย่างอยู่ในโฟลเดอร์โปรเจกต์เหมือนเดิมเป๊ะ (พฤติกรรมไม่เปลี่ยนเลย)
รันจากไฟล์ที่แพ็ก (PyInstaller):
- ไฟล์ประกอบ (fonts/, assets/) ถูกแตกไว้ในโฟลเดอร์ชั่วคราว `sys._MEIPASS` ซึ่ง **อ่านได้อย่างเดียว**
  และหายไปทุกครั้งที่ปิดโปรแกรม
- config.json จึงเขียนลงตรงนั้นไม่ได้ ต้องไปอยู่โฟลเดอร์ตั้งค่าของผู้ใช้ ไม่งั้นค่าที่ตั้งไว้หายทุกรอบ
  (บน macOS ตัว .app อยู่ใน /Applications ซึ่งเขียนไม่ได้อยู่แล้วด้วย)
"""
from __future__ import annotations

import os
import sys

APP_NAME = "NumberSequenceBot"

# PyInstaller ตั้ง sys.frozen ไว้ให้ตอนรันจากไฟล์ที่แพ็กแล้ว
FROZEN = bool(getattr(sys, "frozen", False))

_SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    """โฟลเดอร์ไฟล์ประกอบแบบอ่านอย่างเดียว (fonts/, assets/icons/)."""
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return _SOURCE_DIR


def config_dir() -> str:
    """โฟลเดอร์ที่เขียน config.json ได้จริง."""
    if not FROZEN:
        return _SOURCE_DIR
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    folder = os.path.join(base, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder
