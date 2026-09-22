"""คลิกที่พิกัดจอสัมบูรณ์ (physical px) บน **Windows** — ไม่มี dependency เพิ่ม (macOS ดู mouse_mac.py)

จุดที่อยู่บนหน้าต่าง scrcpy (SDL) — ไม่ขยับเมาส์จริงเลย:
1. `phonetap` แตะตรงเข้ามือถือผ่าน scrcpy-server ตัวที่สอง (ทางหลัก — แม่นทุกครั้ง)
2. ต่อมือถือไม่ได้ → `PostMessage` เข้าหน้าต่าง scrcpy (ทางสำรอง — พลาดเป็นช่วงๆ เพราะ SDL เอา
   WM_MOUSELEAVE มาแทรก ดู _post_click). บนเครื่องผู้ใช้ SendInput ไม่ถึงหน้าต่างไหนเลย จึงใช้ไม่ได้
อย่างอื่น (Chrome / LDPlayer) → `SendInput` ขยับเมาส์จริงไปคลิก ทะลุกรอบโปร่งใสไปโดนหน้าต่างข้างล่างได้
ปกติ (คนละกลไกกับ Qt click-through)
"""
from __future__ import annotations

import atexit
import ctypes
import subprocess
import time
from ctypes import wintypes
from typing import Dict, Optional, Tuple

import phonetap

user32 = ctypes.windll.user32
# instance แยกไว้ตั้ง argtypes ได้โดยไม่กระทบ ctypes.windll.user32 ที่ใช้ร่วมกันทั้ง process — ไม่ตั้ง
# HWND/LPARAM บน x64 จะโดนตัดเหลือ 32 บิต (เคยพลาดมาแล้ว: HWND_TOPMOST = -1 กลายเป็นค่าเพี้ยน)
_u32 = ctypes.WinDLL("user32")
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_u32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.IsIconic.argtypes = [wintypes.HWND]
_u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_u32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

# class ของหน้าต่างที่ต้องคลิกด้วย PostMessage — "SDL_app" = scrcpy (เทสต์แทนค่าเป็น class ของตัวเอง)
POST_CLASSES: tuple[str, ...] = ("SDL_app",)
# ค้างปุ่มไว้เท่านี้ให้มือถือได้แตะที่มีช่วงเวลาจริง (SDL อาจอ่าน down/up รอบเดียวกันจนเป็นแตะ 0ms)
_POST_HOLD_S = 0.03
# ปิดได้ในเทสต์ที่ต้องการทดสอบทาง PostMessage ล้วน
USE_PHONE = True
_phones: Dict[int, phonetap.PhoneTapper] = {}  # pid ของ scrcpy → ช่องแตะมือถือ (ต่อค้างไว้ใช้ทั้งเกม)
# pid ที่ต่อมือถือไม่สำเร็จ → เหตุผล — ไม่ลองต่อใหม่ทุกแตะ (ครั้งละหลายวินาที) จนกว่า prepare() รอบหน้า
_phone_failed: Dict[int, str] = {}


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


def _lparam(x: int, y: int) -> int:
    """พิกัด client แบบ MAKELPARAM — word ละ 16 บิต (ค่าติดลบเก็บเป็น two's complement)."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _post_target_at(x: int, y: int) -> Optional[int]:
    """หน้าต่าง POST_CLASSES บนสุดที่คลุมจุด (x, y) — ไล่ตาม z-order เฉพาะ class นี้ จึงไม่สนกรอบ
    overlay/วงไฮไลต์ของบอทที่ทับอยู่ข้างบน."""
    found: list[int] = []

    @_WNDENUMPROC
    def visit(hwnd, _lparam_unused):
        if not _u32.IsWindowVisible(hwnd) or _u32.IsIconic(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        _u32.GetClassNameW(hwnd, cls, 64)
        if cls.value not in POST_CLASSES:
            return True
        r = wintypes.RECT()
        _u32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.left <= x < r.right and r.top <= y < r.bottom:
            found.append(hwnd)
            return False
        return True

    _u32.EnumWindows(visit, 0)
    return found[0] if found else None


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _phone_for(hwnd: int) -> phonetap.PhoneTapper:
    pid = _window_pid(hwnd)
    if pid in _phone_failed:
        raise phonetap.PhoneTapError(_phone_failed[pid])
    tapper = _phones.get(pid)
    if tapper is None or not tapper.alive:  # ยังไม่เคยต่อ หรือหลุดกลางเกม → ต่อใหม่ครั้งเดียว
        if tapper is not None:
            tapper.close()
        title = ctypes.create_unicode_buffer(256)
        _u32.GetWindowTextW(hwnd, title, 256)
        try:
            tapper = phonetap.PhoneTapper(phonetap.exe_dir_of_pid(pid), title.value).connect()
        except (phonetap.PhoneTapError, OSError, subprocess.SubprocessError) as exc:
            _phones.pop(pid, None)
            _phone_failed[pid] = str(exc)
            raise
        _phones[pid] = tapper
    return tapper


def _frame_fraction(hwnd: int, x: int, y: int, size: Tuple[int, int]) -> Tuple[float, float, bool]:
    """(x, y) บนจอ → ตำแหน่งสัดส่วนบนจอมือถือ (fx, fy, แนวนอนไหม). scrcpy วาดภาพมือถือคงสัดส่วนไว้กลาง
    หน้าต่าง — ถ้าสัดส่วนหน้าต่างไม่ตรงจะมีขอบดำ ต้องหักออกก่อน."""
    r = wintypes.RECT()
    _u32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(x, y)
    _u32.ScreenToClient(hwnd, ctypes.byref(pt))
    cw, ch = max(1, r.right), max(1, r.bottom)
    w, h = size
    landscape = cw > ch
    aspect = (max(w, h) / min(w, h)) if landscape else (min(w, h) / max(w, h))
    content_w = min(cw, ch * aspect)
    content_h = content_w / aspect
    fx = (pt.x + 0.5 - (cw - content_w) / 2) / content_w
    fy = (pt.y + 0.5 - (ch - content_h) / 2) / content_h
    return fx, fy, landscape


def prepare(x: int, y: int) -> str:
    """เตรียมทางคลิกของจุด (x, y) ล่วงหน้า (ต่อมือถือใช้ ~0.5s — ไม่ให้ไปกินเวลาแตะแรก) คืนคำอธิบายไว้ log."""
    hwnd = _post_target_at(x, y)
    if not hwnd:
        return "คลิกด้วยเมาส์ (SendInput)"
    if not USE_PHONE:
        return "คลิกเข้าหน้าต่าง scrcpy (PostMessage)"
    _phone_failed.pop(_window_pid(hwnd), None)  # รอบใหม่ ลองต่อมือถือใหม่
    try:
        return _phone_for(hwnd).describe()
    except (phonetap.PhoneTapError, OSError, subprocess.SubprocessError) as exc:
        return f"ต่อมือถือตรงไม่ได้ ใช้ PostMessage แทน (แตะอาจพลาด): {exc}"


@atexit.register
def close_phones() -> None:
    for tapper in _phones.values():
        tapper.close()
    _phones.clear()


def _post_click(hwnd: int, x: int, y: int, hold_s: float) -> None:
    """แตะด้วย PostMessage (ทางสำรอง) — **ต้องโพสต์ move ติดกับ down และ up ทุกครั้ง**: SDL เอาตำแหน่ง
    กด/ปล่อยจาก move ล่าสุด และ move แรกทำให้ Windows ส่ง WM_MOUSELEAVE (เมาส์จริงไม่ได้อยู่บนหน้าต่าง)
    ซึ่ง SDL จะย้ายตำแหน่งไปที่เมาส์จริง (Pointer location: แบบเว้นช่วงไปโดนมุมขวาบนของจอมือถือ).
    ติดกันแล้วก็ยังแพ้ race ได้ — SDL เป็นอีก process อาจประมวล move ไปก่อนเราโพสต์ down ทัน: เล่นจริง
    เกมไม่รับแตะเป็นช่วงๆ (ช่องเดิมพลาด 2 รอบติด) จึงใช้ phonetap เป็นทางหลัก."""
    pt = wintypes.POINT(x, y)
    _u32.ScreenToClient(hwnd, ctypes.byref(pt))
    lp = _lparam(pt.x, pt.y)
    _u32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    _u32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(hold_s)
    _u32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lp)
    _u32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


def click(x: int, y: int, settle_s: float = 0.01) -> None:
    """คลิกซ้ายที่ (x, y) — ถ้าจุดนั้นอยู่บนหน้าต่าง scrcpy แตะตรงเข้ามือถือ (สำรอง: PostMessage) ไม่ขยับ
    เมาส์จริง ไม่งั้นขยับเมาส์ไปคลิกด้วย SendInput โดย re-pin พิกัดทั้งตอน DOWN และ UP กันพลาดเวลาเมาส์จริง
    ของผู้ใช้ขยับแทรกกลางจังหวะ (แนวทางเดียวกับที่โปรเจกต์พี่น้องเจอปัญหามาแล้ว).
    settle 10ms (เดิม 30ms) — เป้าคือ 50 เลขใน 20 วินาที ทุก ms ต่อคลิกคูณ 50."""
    hwnd = _post_target_at(x, y)
    if hwnd:
        hold_s = max(settle_s, _POST_HOLD_S)
        if USE_PHONE:
            try:
                tapper = _phone_for(hwnd)
                fx, fy, landscape = _frame_fraction(hwnd, x, y, tapper.size)
                tapper.tap(fx, fy, hold_s, landscape)
                return
            except (phonetap.PhoneTapError, OSError, subprocess.SubprocessError):
                pass  # ต่อมือถือไม่ได้/หลุด → ทางสำรอง (prepare() บอกเหตุผลไว้ใน log แล้ว)
        _post_click(hwnd, x, y, hold_s)
        return
    ax, ay = _abs_coords(x, y)
    _send(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    time.sleep(settle_s)
    _send(ax, ay, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE)
    time.sleep(settle_s)
    _send(ax, ay, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE)
