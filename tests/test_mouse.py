"""เทสต์เส้นทางคลิกฝั่ง Windows (mouse_win.py, ไม่ขยับเมาส์จริง) — รัน: .venv\\Scripts\\python.exe tests\\test_mouse.py

ใช้หน้าต่าง Win32 จริงที่วางไว้นอกจอแทน scrcpy: เช็คว่า click() หาหน้าต่างเจอแม้มีหน้าต่างอื่นทับ,
แปลงจุดบนหน้าต่างเป็นสัดส่วนบนจอมือถือถูก (รวมขอบดำ) แล้วส่งให้ phonetap (แทนด้วยตัวปลอม), และทางสำรอง
PostMessage โพสต์ move ติดกับ down/up ด้วยพิกัด client ที่ถูก. ทาง SendInput แทน _send ด้วยตัวจดบันทึก
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform != "win32":  # ทั้งไฟล์ใช้ Win32 API ตรงๆ — ฝั่ง macOS ดู tests/test_mouse_mac.py
    import pytest

    # ต้อง skip ก่อน import ctypes.wintypes — โมดูลนั้น import บนระบบอื่นไม่ได้เลย (ValueError)
    pytest.skip("เทสต์ทางคลิกฝั่ง Windows — รันบน Windows เท่านั้น", allow_module_level=True)

from ctypes import wintypes

import mouse_win as mouse

u = ctypes.WinDLL("user32")
k = ctypes.WinDLL("kernel32")
LRESULT = wintypes.LPARAM
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.DefWindowProcW.restype = LRESULT
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                              wintypes.HINSTANCE, wintypes.LPVOID]
u.CreateWindowExW.restype = wintypes.HWND
u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u.DestroyWindow.argtypes = [wintypes.HWND]
k.GetModuleHandleW.restype = wintypes.HMODULE

TARGET_CLASS = "NumberBotTestPostTarget"
COVER_CLASS = "NumberBotTestCover"
ORIGIN = (-6000, -6000)  # นอกจอ — ไม่โผล่ให้ผู้ใช้เห็น และเมาส์จริงไปไม่ถึง
MOUSE_MSGS = {mouse.WM_MOUSEMOVE, mouse.WM_LBUTTONDOWN, mouse.WM_LBUTTONUP}
received = []


@WNDPROC
def _wndproc(hwnd, msg, wparam, lparam):
    if msg in MOUSE_MSGS:
        received.append((msg, wparam, lparam))
    return u.DefWindowProcW(hwnd, msg, wparam, lparam)


def _register(name: str) -> None:
    wc = WNDCLASSW(lpfnWndProc=_wndproc, hInstance=k.GetModuleHandleW(None), lpszClassName=name)
    u.RegisterClassW(ctypes.byref(wc))


def _window(cls: str, topmost: bool = False) -> int:
    ex = 0x80 | 0x08000000 | (0x8 if topmost else 0)  # TOOLWINDOW | NOACTIVATE | TOPMOST
    return u.CreateWindowExW(ex, cls, cls, 0x80000000 | 0x10000000, ORIGIN[0], ORIGIN[1], 200, 100,
                             None, None, k.GetModuleHandleW(None), None)


def _pump(seconds: float = 0.2) -> None:
    msg = wintypes.MSG()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
            u.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)


def test_lparam_packs_signed_words() -> None:
    assert mouse._lparam(50, 30) == (30 << 16) | 50
    assert mouse._lparam(-5, 3) == (3 << 16) | 0xFFFB
    assert mouse._lparam(70000, 0) == 70000 & 0xFFFF


def test_post_click_pairs_move_with_down_and_up() -> None:
    target = _window(TARGET_CLASS)
    cover = _window(COVER_CLASS, topmost=True)  # แทนกรอบ overlay/วงไฮไลต์ของบอทที่ทับ scrcpy อยู่
    mouse.POST_CLASSES = (TARGET_CLASS,)
    mouse.USE_PHONE = False  # ทดสอบทางสำรอง PostMessage ล้วน
    try:
        assert mouse._post_target_at(ORIGIN[0] + 50, ORIGIN[1] + 30) == target
        assert mouse._post_target_at(ORIGIN[0] + 250, ORIGIN[1] + 30) is None  # นอกหน้าต่าง

        sent = []
        real_send = mouse._send
        mouse._send = lambda *a: sent.append(a)  # SendInput = ขยับเมาส์จริง ทางนี้ต้องไม่แตะเลย
        received.clear()
        try:
            mouse.click(ORIGIN[0] + 50, ORIGIN[1] + 30)
        finally:
            mouse._send = real_send
        _pump()
        lp = mouse._lparam(50, 30)
        assert received == [
            (mouse.WM_MOUSEMOVE, 0, lp),
            (mouse.WM_LBUTTONDOWN, mouse.MK_LBUTTON, lp),
            (mouse.WM_MOUSEMOVE, mouse.MK_LBUTTON, lp),
            (mouse.WM_LBUTTONUP, 0, lp),
        ], received
        assert sent == [], "ทาง PostMessage ต้องไม่ขยับเมาส์จริง (ไม่เรียก SendInput)"

        u.ShowWindow(target, 0)  # SW_HIDE — หน้าต่างที่ซ่อนอยู่ไม่ใช่เป้า
        assert mouse._post_target_at(ORIGIN[0] + 50, ORIGIN[1] + 30) is None
    finally:
        mouse.POST_CLASSES = ("SDL_app",)
        mouse.USE_PHONE = True
        u.DestroyWindow(cover)
        u.DestroyWindow(target)


class FakeTapper:
    def __init__(self) -> None:
        self.alive = True
        self.size = (1260, 2800)
        self.taps = []

    def tap(self, fx, fy, hold_s=0.03, landscape=False) -> None:
        self.taps.append((round(fx, 4), round(fy, 4), landscape))

    def describe(self) -> str:
        return "fake phone"

    def close(self) -> None:
        self.alive = False


def test_scrcpy_window_taps_phone_directly() -> None:
    # หน้าต่าง 200×100 (แนวนอน) แต่มือถือแนวตั้ง 1260×2800 → scrcpy วาดภาพ 200×90 มีขอบดำบนล่าง 5px
    target = _window(TARGET_CLASS)
    mouse.POST_CLASSES = (TARGET_CLASS,)
    fake = FakeTapper()
    mouse._phones[os.getpid()] = fake  # หน้าต่างเทสต์เป็นของ process นี้เอง
    try:
        assert mouse.prepare(ORIGIN[0] + 50, ORIGIN[1] + 30) == "fake phone"
        received.clear()
        mouse.click(ORIGIN[0] + 50, ORIGIN[1] + 30)
        _pump(0.1)
        assert fake.taps == [(round(50.5 / 200, 4), round((30.5 - 5) / 90, 4), True)], fake.taps
        assert received == [], "ทางหลักต้องไม่โพสต์ message เข้าหน้าต่างเลย"
    finally:
        mouse._phones.pop(os.getpid(), None)
        mouse.POST_CLASSES = ("SDL_app",)
        u.DestroyWindow(target)


def test_failed_phone_connect_is_cached_until_next_prepare() -> None:
    # ต่อมือถือไม่ได้ → ใช้ PostMessage แทน และห้ามลองต่อใหม่ทุกแตะ (ครั้งละหลายวินาที) จนกว่าเริ่มรอบใหม่
    attempts = []

    class FailingTapper(FakeTapper):
        def __init__(self, scrcpy_dir, title="") -> None:
            super().__init__()

        def connect(self):
            attempts.append(1)
            raise mouse.phonetap.PhoneTapError("ไม่มีมือถือ (เทสต์)")

    target = _window(TARGET_CLASS)
    mouse.POST_CLASSES = (TARGET_CLASS,)
    real_tapper = mouse.phonetap.PhoneTapper
    mouse.phonetap.PhoneTapper = FailingTapper
    try:
        assert "ไม่มีมือถือ (เทสต์)" in mouse.prepare(ORIGIN[0] + 50, ORIGIN[1] + 30)
        received.clear()
        mouse.click(ORIGIN[0] + 50, ORIGIN[1] + 30)
        mouse.click(ORIGIN[0] + 60, ORIGIN[1] + 30)
        _pump()
        assert len(attempts) == 1, f"ลองต่อ {len(attempts)} ครั้ง"
        assert [m for m, _, _ in received].count(mouse.WM_LBUTTONDOWN) == 2, received
        mouse.prepare(ORIGIN[0] + 50, ORIGIN[1] + 30)  # เริ่มรอบใหม่ → ลองต่อใหม่ได้
        assert len(attempts) == 2
    finally:
        mouse.phonetap.PhoneTapper = real_tapper
        mouse._phone_failed.clear()
        mouse.POST_CLASSES = ("SDL_app",)
        u.DestroyWindow(target)


def test_other_windows_fall_back_to_sendinput() -> None:
    sent = []
    real_send = mouse._send
    mouse._send = lambda dx, dy, flags: sent.append(flags)
    mouse.POST_CLASSES = ("NoSuchWindowClass",)
    try:
        mouse.click(100, 100, settle_s=0)
    finally:
        mouse._send = real_send
        mouse.POST_CLASSES = ("SDL_app",)
    abs_ = mouse.MOUSEEVENTF_ABSOLUTE
    assert sent == [mouse.MOUSEEVENTF_MOVE | abs_, mouse.MOUSEEVENTF_LEFTDOWN | abs_, mouse.MOUSEEVENTF_LEFTUP | abs_]


if __name__ == "__main__":
    _register(TARGET_CLASS)
    _register(COVER_CLASS)
    test_lparam_packs_signed_words()
    test_post_click_pairs_move_with_down_and_up()
    test_scrcpy_window_taps_phone_directly()
    test_failed_phone_connect_is_cached_until_next_prepare()
    test_other_windows_fall_back_to_sendinput()
    print("test_mouse.py OK")
