"""คลิกที่พิกัดจอสัมบูรณ์ (logical points) บน **macOS** — ไม่มี dependency เพิ่ม (Windows ดู mouse_win.py)

จุดที่อยู่บนหน้าต่าง scrcpy — ไม่ขยับเมาส์จริงเลย: `phonetap` แตะตรงเข้ามือถือผ่าน scrcpy-server ตัวที่สอง
(ทางเดียวกับฝั่ง Windows และเป็นทางหลักเหมือนกัน)
อย่างอื่น (Chrome / เอมูเลเตอร์) → CGEvent ขยับเมาส์จริงไปคลิก

**ไม่มีทางสำรองแบบ PostMessage บน macOS**: ระบบไม่ให้ส่ง event เข้าหน้าต่างของแอปอื่นตรงๆ (CGEventPost
ยิงเข้า HID/session ของทั้งเครื่อง ไม่ได้เจาะจงหน้าต่าง) ต่อมือถือไม่ได้จึงตกไปใช้เมาส์จริง ซึ่ง "ได้ผล"
แต่แย่งเมาส์ผู้ใช้และต้องให้หน้าต่าง scrcpy อยู่หน้าสุด — prepare() จึงเตือนไว้ให้เห็นใน log

พิกัดทุกตัวในไฟล์นี้เป็น **logical points** (เหมือน mss และ CGEvent) ไม่ใช่ physical px แบบฝั่ง Windows
— จอ Retina scale 2x ก็ยังเป็นค่าเดียวกัน ดูเหตุผลใน screenmap.py
"""
from __future__ import annotations

import atexit
import subprocess
import time
from typing import Dict, Optional, Tuple

import Quartz

import phonetap

# ชื่อแอปเจ้าของหน้าต่างที่ต้องแตะเข้ามือถือแทนการคลิก (เทสต์แทนค่าเป็นชื่อของตัวเอง)
SCRCPY_OWNERS: Tuple[str, ...] = ("scrcpy",)
# ค้างปุ่มไว้เท่านี้ให้มือถือได้แตะที่มีช่วงเวลาจริง (ค่าเดียวกับฝั่ง Windows)
_TAP_HOLD_S = 0.03
# ปิดได้ในเทสต์ที่ต้องการทดสอบทางเมาส์จริงล้วน
USE_PHONE = True
_phones: Dict[int, phonetap.PhoneTapper] = {}  # pid ของ scrcpy → ช่องแตะมือถือ (ต่อค้างไว้ใช้ทั้งเกม)
# pid ที่ต่อมือถือไม่สำเร็จ → เหตุผล — ไม่ลองต่อใหม่ทุกแตะ (ครั้งละหลายวินาที) จนกว่า prepare() รอบหน้า
_phone_failed: Dict[int, str] = {}

Bounds = Tuple[float, float, float, float]  # (x, y, w, h) ของกรอบหน้าต่างรวมแถบหัว

# ช่วงความสูงแถบหัวหน้าต่างที่ยอมรับว่าเป็นค่าจริง (points) — กันไม่ให้ค่าที่คำนวณจากสัดส่วนเพี้ยนไปไกล
_MIN_TITLEBAR, _MAX_TITLEBAR = 16.0, 64.0


def _system_titlebar_h() -> float:
    """ความสูงแถบหัวหน้าต่างมาตรฐานของระบบ — ใช้เป็นทางสำรองเมื่อคำนวณจากสัดส่วนภาพไม่ได้."""
    try:
        import AppKit

        mask = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
                | AppKit.NSWindowStyleMaskMiniaturizable | AppKit.NSWindowStyleMaskResizable)
        frame = AppKit.NSWindow.frameRectForContentRect_styleMask_(((0.0, 0.0), (100.0, 100.0)), mask)
        return float(frame[1][1]) - 100.0
    except Exception:
        return 28.0


def _windows_front_to_back() -> list:
    return Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []


def _scrcpy_window_at(x: int, y: int) -> Optional[Tuple[int, str, Bounds]]:
    """(pid, ชื่อหน้าต่าง, กรอบ) ของหน้าต่าง scrcpy บนสุดที่คลุมจุด (x, y)

    CGWindowList คืนรายการเรียงจากหน้าไปหลังอยู่แล้ว และเรากรองเอาเฉพาะแอป scrcpy จึงไม่สนกรอบ
    overlay/วงไฮไลต์ของบอทที่ทับอยู่ข้างบน (เหมือนที่ฝั่ง Windows ไล่ z-order เฉพาะ class เดียว)
    """
    for info in _windows_front_to_back():
        owner = info.get("kCGWindowOwnerName") or ""
        if owner not in SCRCPY_OWNERS:
            continue
        b = info.get("kCGWindowBounds")
        if not b:
            continue
        bx, by, bw, bh = float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"])
        if bx <= x < bx + bw and by <= y < by + bh:
            return int(info.get("kCGWindowOwnerPID", 0)), (info.get("kCGWindowName") or ""), (bx, by, bw, bh)
    return None


def _phone_for(pid: int, title: str) -> phonetap.PhoneTapper:
    if pid in _phone_failed:
        raise phonetap.PhoneTapError(_phone_failed[pid])
    tapper = _phones.get(pid)
    if tapper is None or not tapper.alive:  # ยังไม่เคยต่อ หรือหลุดกลางเกม → ต่อใหม่ครั้งเดียว
        if tapper is not None:
            tapper.close()
        try:
            tapper = phonetap.PhoneTapper(phonetap.exe_dir_of_pid(pid), title).connect()
        except (phonetap.PhoneTapError, OSError, subprocess.SubprocessError) as exc:
            _phones.pop(pid, None)
            _phone_failed[pid] = str(exc)
            raise
        _phones[pid] = tapper
    return tapper


def _titlebar_h(bounds: Bounds, size: Tuple[int, int], landscape: bool) -> float:
    """ความสูงแถบหัวของหน้าต่าง scrcpy นี้ — CGWindowBounds รวมแถบหัวมาด้วย (ต่างจาก GetClientRect
    ของ Windows ที่ได้พื้นที่วาดล้วน) จึงต้องหักออกก่อนถึงจะได้กรอบภาพมือถือ

    ปกติ scrcpy ย่อ/ขยายหน้าต่างให้พอดีสัดส่วนจอมือถือเอง (ไม่มีขอบดำ) ความสูงแถบหัวจึงเท่ากับส่วนที่เกิน
    จากสัดส่วนพอดีเป๊ะ — **วัดแบบนี้แม่นกว่าค่าคงที่ของระบบ**: วัดหน้าต่าง scrcpy จริงบน macOS 26 ได้ 32pt
    (ขอหน้าต่างขนาด 400×700 แล้วได้กรอบ 315×732 = ภาพ 315×700 พอดีสัดส่วน + แถบหัว 32) แต่ทั้ง
    NSWindow.frameRectForContentRect และ NSWindow จริงๆ ต่างคืน 28pt — หน้าต่างของ SDL ไม่เท่ากับ
    หน้าต่างมาตรฐาน จึงเอาค่าจากระบบมาใช้ตรงๆ ไม่ได้

    ข้อจำกัด: ถ้าผู้ใช้ลากหน้าต่างให้ "สูงเกิน" สัดส่วนจนมีขอบดำบนล่าง รูปทรงที่ได้จะแยกไม่ออกระหว่าง
    "แถบหัวสูง + ไม่มีขอบดำ" กับ "แถบหัวเตี้ย + มีขอบดำ" (สองคำอธิบายให้กรอบหน้าต่างหน้าตาเดียวกันเป๊ะ)
    ที่นี่เลือกทางแรกเพราะ scrcpy ตั้งขนาดพอดีสัดส่วนมาให้เองตั้งแต่เปิด — ผลคือถ้าไปลากขยายเองแนวตั้ง
    จุดแตะจะเลื่อนลงเท่าความสูงขอบดำ แนะนำให้ปล่อยขนาดหน้าต่างตามที่ scrcpy ตั้งมา
    ส่วนกรณีลากให้ "กว้างเกิน" (ขอบดำซ้ายขวา) ค่าที่คำนวณได้จะหลุดช่วงจนรู้ตัว → ใช้ค่ามาตรฐานของระบบแทน
    แล้วปล่อยให้ _frame_fraction หักขอบดำต่อตามปกติ
    """
    _, _, bw, bh = bounds
    w, h = size
    if landscape and w < h:
        w, h = h, w
    aspect = w / h if h else 1.0
    fitted = bh - (bw / aspect if aspect else bh)
    if _MIN_TITLEBAR <= fitted <= _MAX_TITLEBAR:
        return round(fitted)
    return _system_titlebar_h()


def _frame_fraction(bounds: Bounds, x: int, y: int, size: Tuple[int, int]) -> Tuple[float, float, bool]:
    """(x, y) บนจอ → ตำแหน่งสัดส่วนบนจอมือถือ (fx, fy, แนวนอนไหม). scrcpy วาดภาพมือถือคงสัดส่วนไว้กลาง
    พื้นที่วาด — ถ้าสัดส่วนหน้าต่างไม่ตรงจะมีขอบดำ ต้องหักออกก่อน (ตรรกะเดียวกับฝั่ง Windows)."""
    bx, by, bw, bh = bounds
    landscape = bw > bh
    titlebar = _titlebar_h(bounds, size, landscape)
    cw = max(1.0, bw)
    ch = max(1.0, bh - titlebar)
    # พิกัดภายในพื้นที่วาด (นับจากใต้แถบหัว) — เทียบเท่า ScreenToClient ของ Windows
    px = x - bx
    py = y - by - titlebar
    w, h = size
    aspect = (max(w, h) / min(w, h)) if landscape else (min(w, h) / max(w, h))
    content_w = min(cw, ch * aspect)
    content_h = content_w / aspect
    fx = (px + 0.5 - (cw - content_w) / 2) / content_w
    fy = (py + 0.5 - (ch - content_h) / 2) / content_h
    return fx, fy, landscape


def prepare(x: int, y: int) -> str:
    """เตรียมทางคลิกของจุด (x, y) ล่วงหน้า (ต่อมือถือใช้ ~0.5s — ไม่ให้ไปกินเวลาแตะแรก) คืนคำอธิบายไว้ log."""
    found = _scrcpy_window_at(x, y)
    if not found:
        return "คลิกด้วยเมาส์ (CGEvent)"
    pid, title, _ = found
    if not USE_PHONE:
        return "คลิกด้วยเมาส์ (CGEvent) — ปิดการแตะมือถือไว้"
    _phone_failed.pop(pid, None)  # รอบใหม่ ลองต่อมือถือใหม่
    try:
        return _phone_for(pid, title).describe()
    except (phonetap.PhoneTapError, OSError, subprocess.SubprocessError) as exc:
        return (f"ต่อมือถือตรงไม่ได้ ใช้เมาส์จริงคลิกแทน (ต้องให้หน้าต่าง scrcpy อยู่หน้าสุด "
                f"และห้ามขยับเมาส์เอง): {exc}")


@atexit.register
def close_phones() -> None:
    for tapper in _phones.values():
        tapper.close()
    _phones.clear()


def _post(event_type: int, x: int, y: int) -> None:
    event = Quartz.CGEventCreateMouseEvent(None, event_type, (float(x), float(y)),
                                           Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def move(x: int, y: int) -> None:
    _post(Quartz.kCGEventMouseMoved, x, y)


def _real_click(x: int, y: int, settle_s: float) -> None:
    """คลิกด้วยเมาส์จริง — re-pin พิกัดทั้งตอน down และ up กันพลาดเวลาเมาส์จริงของผู้ใช้ขยับแทรกกลางจังหวะ."""
    _post(Quartz.kCGEventMouseMoved, x, y)
    time.sleep(settle_s)
    _post(Quartz.kCGEventLeftMouseDown, x, y)
    time.sleep(settle_s)
    _post(Quartz.kCGEventLeftMouseUp, x, y)


def click(x: int, y: int, settle_s: float = 0.01) -> None:
    """คลิกซ้ายที่ (x, y) — ถ้าจุดนั้นอยู่บนหน้าต่าง scrcpy แตะตรงเข้ามือถือโดยไม่ขยับเมาส์จริง
    ไม่งั้น (หรือต่อมือถือไม่ได้) ขยับเมาส์ไปคลิกด้วย CGEvent
    settle 10ms — เป้าคือ 50 เลขใน 20 วินาที ทุก ms ต่อคลิกคูณ 50."""
    found = _scrcpy_window_at(x, y)
    if found and USE_PHONE:
        pid, title, bounds = found
        try:
            tapper = _phone_for(pid, title)
            fx, fy, landscape = _frame_fraction(bounds, x, y, tapper.size)
            tapper.tap(fx, fy, max(settle_s, _TAP_HOLD_S), landscape)
            return
        except (phonetap.PhoneTapError, OSError, subprocess.SubprocessError):
            pass  # ต่อมือถือไม่ได้/หลุด → ทางสำรอง (prepare() บอกเหตุผลไว้ใน log แล้ว)
    _real_click(x, y, settle_s)
