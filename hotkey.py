"""ปุ่มหยุดฉุกเฉิน (panic key) ที่กดได้จากทุกหน้าต่าง — คนละกลไกกันในแต่ละระบบ

Windows: ไลบรารี `keyboard` (ทำงานได้เลย บางเครื่องต้องรันแบบ Administrator)
macOS:   CGEventTap ของ Quartz — `keyboard` บน macOS บังคับให้รันด้วย root (ไม่งั้น thread ที่มันปั่นขึ้นมา
         โยน OSError("Error 13 - Must be run as administrator") ทิ้งไว้) จึงไม่แตะไลบรารีนั้นเลย
         ต้องเปิดสิทธิ์ Accessibility ให้โปรแกรมที่รันบอท (System Settings → Privacy & Security →
         Accessibility) ไม่งั้นระบบไม่ให้ดักปุ่ม — ฟังก์ชันจะโยน HotkeyError บอกเหตุผลให้เอาไปขึ้น log

ดักแบบ "ฟังอย่างเดียว" (listen-only) ไม่กลืนปุ่ม — Esc ยังถึงแอปที่โฟกัสอยู่ตามปกติ
"""
from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"


class HotkeyError(RuntimeError):
    pass


# ---- Windows ---------------------------------------------------------------
def _register_windows(key: str, callback: Callable[[], None]) -> str:
    try:
        import keyboard
    except Exception as exc:  # pragma: no cover — เครื่องที่ยังไม่ได้ pip install
        raise HotkeyError(f"ไลบรารี keyboard ใช้ไม่ได้ ({exc}) — pip install keyboard") from exc
    keyboard.add_hotkey(key, callback)
    return f"กด {key} หยุดได้จากทุกหน้าต่าง"


def _unregister_windows(key: str) -> None:
    try:
        import keyboard

        keyboard.remove_hotkey(key)
    except Exception:
        pass


# ---- macOS -----------------------------------------------------------------
# virtual keycode ของ macOS (ชุดเท่าที่พอใช้เป็นปุ่มหยุด — ปุ่มอื่นจะฟ้องว่าไม่รองรับ)
_MAC_KEYCODES = {
    "esc": 53, "escape": 53, "space": 49, "tab": 48, "enter": 36, "return": 36, "delete": 51,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4, "i": 34, "j": 38, "k": 40,
    "l": 37, "m": 46, "n": 45, "o": 31, "p": 35, "q": 12, "r": 15, "s": 1, "t": 17, "u": 32,
    "v": 9, "w": 13, "x": 7, "y": 16, "z": 6,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
}

_mac_stop: Optional[Callable[[], None]] = None


def _register_darwin(key: str, callback: Callable[[], None]) -> str:
    import ApplicationServices
    import Quartz

    code = _MAC_KEYCODES.get(key.strip().lower())
    if code is None:
        raise HotkeyError(f"ยังไม่รองรับปุ่ม {key!r} บน macOS (ใช้ esc, f1–f12, ตัวอักษร หรือตัวเลข)")
    if not ApplicationServices.AXIsProcessTrusted():
        raise HotkeyError("ยังไม่ได้เปิดสิทธิ์ Accessibility — เปิดที่ System Settings → Privacy & "
                          "Security → Accessibility แล้วเปิดบอทใหม่")

    def on_event(proxy, event_type, event, refcon):
        # ระบบปิด tap เองได้เมื่อ callback ช้า — เปิดกลับทันที ไม่งั้นปุ่มหยุดเงียบไปทั้งรอบ
        if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(tap, True)
            return event
        if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode) == code:
            try:
                callback()
            except Exception:
                pass
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,  # ไม่กลืนปุ่ม — แอปที่โฟกัสอยู่ยังได้รับตามปกติ
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown), on_event, None)
    if tap is None:
        raise HotkeyError("สร้างตัวดักปุ่มไม่ได้ (ระบบไม่อนุญาต) — ตรวจสิทธิ์ Accessibility")

    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    ready = threading.Event()
    box: dict = {}

    def pump() -> None:
        loop = Quartz.CFRunLoopGetCurrent()
        box["loop"] = loop
        Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        ready.set()
        Quartz.CFRunLoopRun()  # วนอยู่ใน thread นี้จนกว่าจะสั่งหยุด

    # daemon — ปิดโปรแกรมได้เลยแม้ลืมเรียก unregister()
    threading.Thread(target=pump, name="panic-key", daemon=True).start()
    ready.wait(2.0)

    global _mac_stop

    def stop() -> None:
        Quartz.CGEventTapEnable(tap, False)
        loop = box.get("loop")
        if loop is not None:
            Quartz.CFRunLoopStop(loop)

    _mac_stop = stop
    return f"กด {key} หยุดได้จากทุกหน้าต่าง"


def _unregister_darwin(_key: str) -> None:
    global _mac_stop
    if _mac_stop is not None:
        try:
            _mac_stop()
        except Exception:
            pass
        _mac_stop = None


# ---- หน้าตาที่ใช้ร่วมกัน ------------------------------------------------------
def register(key: str, callback: Callable[[], None]) -> str:
    """ดักปุ่ม `key` ทั้งเครื่อง แล้วเรียก `callback` — คืนข้อความอธิบายไว้ขึ้น log
    โยน HotkeyError เมื่อดักไม่ได้ (ผู้เรียกควรเตือนผู้ใช้แล้วทำงานต่อ ไม่ใช่ล้มทั้งโปรแกรม)."""
    if IS_WINDOWS:
        return _register_windows(key, callback)
    if sys.platform == "darwin":
        return _register_darwin(key, callback)
    raise HotkeyError(f"ยังไม่รองรับระบบปฏิบัติการ {sys.platform!r}")


def unregister(key: str) -> None:
    if IS_WINDOWS:
        _unregister_windows(key)
    elif sys.platform == "darwin":
        _unregister_darwin(key)
