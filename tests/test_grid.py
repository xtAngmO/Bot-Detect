"""เทสต์อ่านตาราง 5x5 ทั้งก้อน (จำลองกรอบตาราง) — รัน: .venv\\Scripts\\python.exe tests\\test_grid.py
สุ่มตำแหน่งเลขใหม่ทุกครั้งที่รัน — คาดหวังว่าต้องอ่านครบทั้ง 25 ช่องเสมอ (มี valid_max=25 ช่วยกรอง
ค่าที่เป็นไปไม่ได้ + fallback psm 8 กันพลาด — ดูเหตุผลเต็มๆ ใน capture.read_number_robust)"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont

import capture

capture.configure_tesseract("")

ROWS, COLS = 5, 5
CELL = 100
GAP = 14


def _build_grid_image():
    img = Image.new("RGB", (CELL * COLS, CELL * ROWS), "#e5e5e5")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 42)
    except Exception:
        font = ImageFont.load_default()

    nums = list(range(1, ROWS * COLS + 1))
    random.shuffle(nums)
    i = 0
    for r in range(ROWS):
        for c in range(COLS):
            n = nums[i]
            i += 1
            x0, y0 = c * CELL + GAP // 2, r * CELL + GAP // 2
            x1, y1 = (c + 1) * CELL - GAP // 2, (r + 1) * CELL - GAP // 2
            d.rounded_rectangle((x0, y0, x1, y1), radius=10, fill="white")
            bbox = d.textbbox((0, 0), str(n), font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = x0 + ((x1 - x0) - tw) / 2 - bbox[0]
            ty = y0 + ((y1 - y0) - th) / 2 - bbox[1]
            d.text((tx, ty), str(n), fill="black", font=font)
    return img


def test_read_grid_all_25() -> None:
    img = _build_grid_image()
    orig_grab = capture.grab
    capture.grab = lambda rect: img
    try:
        result = capture.read_grid_numbers(
            (0, 0, CELL * COLS, CELL * ROWS), ROWS, COLS, max_number=ROWS * COLS
        )
    finally:
        capture.grab = orig_grab
    missing = set(range(1, ROWS * COLS + 1)) - set(result.keys())
    assert not missing, f"missing numbers: {missing}"


if __name__ == "__main__":
    test_read_grid_all_25()
    print("test_grid.py OK")
