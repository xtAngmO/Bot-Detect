"""เทสต์ OCR กับภาพจากเกมจริง (จับจากจอ scale 125%) — รัน: .venv\\Scripts\\python.exe tests\\test_real_capture.py

fixtures ตัดมาจากสกรีนช็อตที่ผู้ใช้ส่งมาตอนบอทขึ้น "อ่านเลขต่อไปไม่ออก" ทั้งที่กรอบวางถูกที่:
- real_next_125.png — กรอบเลขต่อไปจริง มีป้าย "เลขต่อไป" ภาษาไทย + เส้นขอบ overlay สีเขียวพาดทับด้วย
  (mss จับหน้าต่าง overlay ติดมา) ซึ่งทำให้ pipeline เดิมอ่านได้ None
- real_grid_125.png — ตาราง 5×5 ฟอนต์หนาของเกม ซึ่ง pipeline เดิม (อัปสเกลตายตัว 4 เท่า) อ่านเลข 8 ไม่ออก
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

import capture

capture.configure_tesseract("")

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
EXPECTED_GRID = [
    [19, 10, 28, 12, 25],
    [24, 16, 30, 17, 6],
    [26, 20, 9, 15, 27],
    [21, 13, 18, 11, 29],
    [8, 22, 14, 7, 23],
]


def test_real_next_box_with_label_and_overlay_line() -> None:
    img = Image.open(os.path.join(FIXTURES, "real_next_125.png")).convert("RGB")
    result = capture.read_number_robust(img, valid_max=50)
    assert result == 6, f"expected 6, got {result}"


def test_real_grid_all_25() -> None:
    img = Image.open(os.path.join(FIXTURES, "real_grid_125.png")).convert("RGB")
    orig_grab = capture.grab
    capture.grab = lambda rect: img
    try:
        result = capture.read_grid_numbers((0, 0, img.width, img.height), 5, 5, max_number=50)
    finally:
        capture.grab = orig_grab
    cell_w, cell_h = img.width / 5, img.height / 5
    got = [[None] * 5 for _ in range(5)]
    for num, (cx, cy) in result.items():
        got[int(cy // cell_h)][int(cx // cell_w)] = num
    assert got == EXPECTED_GRID, f"grid mismatch:\n{got}"


if __name__ == "__main__":
    test_real_next_box_with_label_and_overlay_line()
    test_real_grid_all_25()
    print("test_real_capture.py OK")
