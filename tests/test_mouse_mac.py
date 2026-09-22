"""เทสต์เส้นทางคลิกฝั่ง macOS (mouse_mac.py, ไม่ขยับเมาส์จริง) — รัน: .venv/bin/python tests/test_mouse_mac.py

แทน CGWindowList ด้วยรายการปลอม จึงไม่ต้องเปิด scrcpy จริงตอนเทสต์ ตัวเลขกรอบหน้าต่างในไฟล์นี้วัดมาจาก
scrcpy 4.1 จริงบน macOS 26 (หน้าต่าง 139×341 คู่กับมือถือ 1260×2800) — ไว้กันค่าความสูงแถบหัวหน้าต่างเพี้ยน
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform != "darwin":  # ต้องมี Quartz — ฝั่ง Windows ดู tests/test_mouse.py
    import pytest

    pytest.skip("เทสต์ทางคลิกฝั่ง macOS — รันบน macOS เท่านั้น", allow_module_level=True)

import mouse_mac as mouse

# ค่าที่วัดจาก scrcpy จริง: scrcpy ย่อหน้าต่างให้พอดีสัดส่วนมือถือเอง (ไม่มีขอบดำ) แถบหัวสูง 32
REAL_BOUNDS = (100.0, 68.0, 139.0, 341.0)
PHONE = (1260, 2800)
OWNER = "scrcpy"


def _fake_window(pid: int, name: str, bounds, owner: str = OWNER) -> dict:
    x, y, w, h = bounds
    return {"kCGWindowOwnerName": owner, "kCGWindowName": name, "kCGWindowOwnerPID": pid,
            "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


class FakeTapper:
    def __init__(self) -> None:
        self.alive = True
        self.size = PHONE
        self.taps = []

    def tap(self, fx, fy, hold_s=0.03, landscape=False) -> None:
        self.taps.append((round(fx, 4), round(fy, 4), landscape))

    def describe(self) -> str:
        return "fake phone"

    def close(self) -> None:
        self.alive = False


def test_titlebar_measured_from_aspect_fit() -> None:
    # หน้าต่างพอดีสัดส่วน → คำนวณความสูงแถบหัวได้ตรงกับที่วัดจริง (32) ไม่ใช่ค่ามาตรฐานของระบบ (28)
    assert mouse._titlebar_h(REAL_BOUNDS, PHONE, landscape=False) == 32
    # หน้าต่างที่ผู้ใช้ลากขยายเองจนมีขอบดำ → ค่าที่คำนวณหลุดช่วง ต้องถอยไปใช้ค่ามาตรฐานของระบบ
    stretched = (100.0, 68.0, 139.0, 900.0)
    assert mouse._titlebar_h(stretched, PHONE, landscape=False) == mouse._system_titlebar_h()


def test_frame_fraction_matches_real_window() -> None:
    # พื้นที่วาดคือ 139×309 เริ่มที่ (100, 100) — กลางภาพต้องได้กลางจอมือถือเป๊ะ
    fx, fy, landscape = mouse._frame_fraction(REAL_BOUNDS, 169, 254, PHONE)
    assert (round(fx, 4), round(fy, 4), landscape) == (0.5, 0.5, False)
    # มุมบนซ้ายและล่างขวาต้องอยู่ในจอมือถือ ไม่ทะลุออกนอก [0, 1]
    tl = mouse._frame_fraction(REAL_BOUNDS, 100, 100, PHONE)
    br = mouse._frame_fraction(REAL_BOUNDS, 238, 408, PHONE)
    assert 0.0 <= tl[0] < 0.01 and 0.0 <= tl[1] < 0.01, tl
    assert 0.99 < br[0] <= 1.0 and 0.99 < br[1] <= 1.0, br


def test_frame_fraction_removes_letterbox_bars() -> None:
    # หน้าต่างที่ผู้ใช้ลากให้กว้างเกินสัดส่วนมือถือ → scrcpy วาดภาพไว้กลาง มีขอบดำซ้ายขวา ต้องหักออก
    bar = mouse._system_titlebar_h()
    bounds = (0.0, 0.0, 400.0, 100.0 + bar)
    # คำนวณจากสัดส่วนแล้วติดลบ (หน้าต่างกว้างเกินกว่าจะพอดีได้) → ถอยไปใช้ค่ามาตรฐานของระบบ
    assert mouse._titlebar_h(bounds, PHONE, landscape=True) == bar

    aspect = 2800 / 1260  # มือถือวางแนวนอน
    content_w = 100.0 * aspect  # พื้นที่วาดสูง 100 → ภาพกว้างเท่านี้ ที่เหลือเป็นขอบดำ
    left_bar = (400.0 - content_w) / 2
    fx, fy, landscape = mouse._frame_fraction(bounds, 200, int(bar) + 50, PHONE)
    assert landscape is True
    assert round(fx, 4) == round((200.5 - left_bar) / content_w, 4)
    assert round(fy, 4) == round(50.5 / 100.0, 4)


def test_picks_scrcpy_window_under_overlays() -> None:
    # รายการเรียงจากหน้าไปหลัง: overlay ของบอทอยู่บนสุด แต่ต้องข้ามไปเจอหน้าต่าง scrcpy ข้างล่าง
    windows = [
        _fake_window(999, "overlay", REAL_BOUNDS, owner="Python"),
        _fake_window(4845, "BOTPROBE", REAL_BOUNDS),
    ]
    real = mouse._windows_front_to_back
    mouse._windows_front_to_back = lambda: windows
    try:
        assert mouse._scrcpy_window_at(169, 254) == (4845, "BOTPROBE", REAL_BOUNDS)
        assert mouse._scrcpy_window_at(1400, 900) is None  # นอกหน้าต่าง
    finally:
        mouse._windows_front_to_back = real


def test_scrcpy_window_taps_phone_without_moving_mouse() -> None:
    windows = [_fake_window(4845, "BOTPROBE", REAL_BOUNDS)]
    fake = FakeTapper()
    posted = []
    real_windows, real_post = mouse._windows_front_to_back, mouse._post
    mouse._windows_front_to_back = lambda: windows
    mouse._post = lambda *a: posted.append(a)  # CGEvent = ขยับเมาส์จริง ทางนี้ต้องไม่แตะเลย
    mouse._phones[4845] = fake
    try:
        assert mouse.prepare(169, 254) == "fake phone"
        mouse.click(169, 254)
        assert fake.taps == [(0.5, 0.5, False)], fake.taps
        assert posted == [], "ทางแตะมือถือต้องไม่ขยับเมาส์จริง"
    finally:
        mouse._phones.pop(4845, None)
        mouse._windows_front_to_back, mouse._post = real_windows, real_post


def test_other_windows_fall_back_to_real_click() -> None:
    import Quartz

    posted = []
    real_windows, real_post = mouse._windows_front_to_back, mouse._post
    mouse._windows_front_to_back = lambda: []
    mouse._post = lambda ev, x, y: posted.append((ev, x, y))
    try:
        mouse.click(100, 100, settle_s=0)
    finally:
        mouse._windows_front_to_back, mouse._post = real_windows, real_post
    assert posted == [(Quartz.kCGEventMouseMoved, 100, 100),
                      (Quartz.kCGEventLeftMouseDown, 100, 100),
                      (Quartz.kCGEventLeftMouseUp, 100, 100)], posted


def test_failed_phone_connect_is_cached_until_next_prepare() -> None:
    # ต่อมือถือไม่ได้ → ใช้เมาส์จริงแทน และห้ามลองต่อใหม่ทุกแตะ (ครั้งละหลายวินาที) จนกว่าเริ่มรอบใหม่
    import phonetap

    attempts = []
    windows = [_fake_window(4845, "BOTPROBE", REAL_BOUNDS)]
    posted = []

    class FailingTapper:
        def __init__(self, scrcpy_dir, title="") -> None:
            pass

        def connect(self):
            attempts.append(1)
            raise phonetap.PhoneTapError("ไม่มีมือถือ (เทสต์)")

    real_windows, real_post = mouse._windows_front_to_back, mouse._post
    real_tapper, real_dir = phonetap.PhoneTapper, phonetap.exe_dir_of_pid
    mouse._windows_front_to_back = lambda: windows
    mouse._post = lambda ev, x, y: posted.append(ev)
    phonetap.PhoneTapper = FailingTapper
    phonetap.exe_dir_of_pid = lambda pid: "/nonexistent"
    try:
        assert "ไม่มีมือถือ (เทสต์)" in mouse.prepare(169, 254)
        mouse.click(169, 254)
        mouse.click(170, 254)
        assert len(attempts) == 1, f"ลองต่อ {len(attempts)} ครั้ง"
        assert posted.count(__import__("Quartz").kCGEventLeftMouseDown) == 2, posted
        mouse.prepare(169, 254)  # เริ่มรอบใหม่ → ลองต่อใหม่ได้
        assert len(attempts) == 2
    finally:
        mouse._windows_front_to_back, mouse._post = real_windows, real_post
        phonetap.PhoneTapper, phonetap.exe_dir_of_pid = real_tapper, real_dir
        mouse._phone_failed.clear()


if __name__ == "__main__":
    test_titlebar_measured_from_aspect_fit()
    test_frame_fraction_matches_real_window()
    test_frame_fraction_removes_letterbox_bars()
    test_picks_scrcpy_window_under_overlays()
    test_scrcpy_window_taps_phone_without_moving_mouse()
    test_other_windows_fall_back_to_real_click()
    test_failed_phone_connect_is_cached_until_next_prepare()
    print("test_mouse_mac.py OK")
