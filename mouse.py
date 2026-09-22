"""คลิกเมาส์ที่พิกัดจอสัมบูรณ์ผ่าน ctypes SendInput (Windows) — ไม่มี dependency เพิ่ม
คลิกทะลุกรอบโปร่งใสไปโดนหน้าต่าง LDPlayer ข้างล่างได้ปกติ (คนละกลไกกับ Qt click-through)
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUTUnion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUnion)]


def _abs_coords(x: int, y: int) -> tuple[int, int]:
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    sw = sw or 1
    sh = sh or 1
    return int(x * 65535 / sw), int(y * 65535 / sh)


def _send(dx: int, dy: int, flags: int) -> None:
    mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
    inp = INPUT(type=INPUT_MOUSE, u=_INPUTUnion(mi=mi))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def move(x: int, y: int) -> None:
    ax, ay = _abs_coords(x, y)
    _send(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)


def click(x: int, y: int, settle_s: float = 0.01) -> None:
    """ขยับเมาส์ไปที่ (x, y) แล้วคลิกซ้าย — re-pin พิกัดทั้งตอน DOWN และ UP กันพลาด
    เวลาเมาส์จริงของผู้ใช้ขยับแทรกกลางจังหวะ (แนวทางเดียวกับที่โปรเจกต์พี่น้องเจอปัญหามาแล้ว).
    settle 10ms (เดิม 30ms) — เป้าคือ 50 เลขใน 20 วินาที ทุก ms ต่อคลิกคูณ 50."""
    ax, ay = _abs_coords(x, y)
    _send(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    time.sleep(settle_s)
    _send(ax, ay, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE)
    time.sleep(settle_s)
    _send(ax, ay, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE)
