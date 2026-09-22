"""เทสต์ OCR กับภาพจากเกมจริง (จับจากจอ scale 125%) — รัน: .venv\\Scripts\\python.exe tests\\test_real_capture.py

fixtures ตัดมาจากสกรีนช็อตที่ผู้ใช้ส่งมาตอนบอทขึ้น "อ่านเลขต่อไปไม่ออก" ทั้งที่กรอบวางถูกที่:
- real_next_125.png — กรอบเลขต่อไปจริง มีป้าย "เลขต่อไป" ภาษาไทย + เส้นขอบ overlay สีเขียวพาดทับด้วย
  (mss จับหน้าต่าง overlay ติดมา) ซึ่งทำให้ pipeline เดิมอ่านได้ None
- real_grid_125.png — ตาราง 5×5 ฟอนต์หนาของเกม ซึ่ง pipeline เดิม (อัปสเกลตายตัว 4 เท่า) อ่านเลข 8 ไม่ออก
- real_grid_scrcpy.png / real_next_scrcpy.png — เกมบนมือถือจริงผ่านหน้าต่าง scrcpy (ฟอนต์ Android ตัวเลข
  สูง ~20px) ตัดจากสกรีนช็อตของผู้ใช้ตรงพื้นที่ในกรอบ overlay พอดี (= ภาพที่บอทจับได้จริง)
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

import capture
from config import Settings
from solver import Solver

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


SCRCPY_GRID = [
    [10, 12, 28, 26, 21],
    [14, 20, 9, 22, 25],
    [16, 30, 11, 6, 19],
    [24, 23, 13, 8, 29],
    [15, 17, 27, 18, 7],
]
SCRCPY_WHERE = {SCRCPY_GRID[r][c]: (r, c) for r in range(5) for c in range(5)}


def _fixture(name: str, scale: float = 1.0, jpeg: int = 0) -> Image.Image:
    img = Image.open(os.path.join(FIXTURES, name)).convert("RGB")
    if scale != 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    if jpeg:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=jpeg)
        img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    return img


def _sync(grid: Image.Image, nxt: Image.Image):
    """Solver._sync ตัวจริง (OCR จริง + gridsolve) กับภาพนิ่ง แทน capture.grab."""
    grid_rect = (0, 0, grid.width, grid.height)
    next_rect = (5000, 0, nxt.width, nxt.height)
    orig = capture.grab
    capture.grab = lambda rect: grid if rect == grid_rect else nxt
    try:
        bot = Solver(Settings(grid_box=grid_rect, next_box=next_rect, max_number=50))
        logs = []
        bot.log.connect(lambda level, msg: logs.append(msg))
        return bot._sync(grid_rect), logs
    finally:
        capture.grab = orig


def test_scrcpy_next_box() -> None:
    assert capture.read_number_robust(_fixture("real_next_scrcpy.png"), valid_max=50, parallel=True) == 6


def test_scrcpy_grid_sync() -> None:
    (nxt, where), logs = _sync(_fixture("real_grid_scrcpy.png"), _fixture("real_next_scrcpy.png"))
    assert nxt == 6 and where == SCRCPY_WHERE, (nxt, where, logs)


def test_scrcpy_grid_sync_degraded() -> None:
    # ย่อ 0.65 + JPEG 60 — OCR ทีละช่องอ่าน 15 เป็น 18 แบบมั่นใจ; _sync ต้องจับได้และแก้ให้ถูกครบ
    (nxt, where), logs = _sync(_fixture("real_grid_scrcpy.png", 0.65, 60), _fixture("real_next_scrcpy.png", 0.65, 60))
    assert nxt == 6 and where == SCRCPY_WHERE, (nxt, where, logs)


def test_grid_similar_ignores_video_noise_but_not_one_changed_cell() -> None:
    # ใช้ตัดสินว่าผลอ่านล่วงหน้า (standby) ยังใช้ได้ตอนกดเริ่มไหม — วัดกับภาพ scrcpy จริง
    grid = _fixture("real_grid_scrcpy.png")
    cw, ch = grid.width / 5, grid.height / 5

    def moved(src, dst) -> Image.Image:
        (sr, sc), (dr, dc) = src, dst
        img = grid.copy()
        img.paste(grid.crop((int(sc * cw), int(sr * ch), int((sc + 1) * cw), int((sr + 1) * ch))),
                  (int(dc * cw), int(dr * ch)))
        return img

    def jpeg(img: Image.Image, quality: int) -> Image.Image:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")

    assert capture.grid_similar(grid, jpeg(grid, 30), 5, 5)  # noise วิดีโอหนักๆ ของภาพเดิม
    assert not capture.grid_similar(grid, moved((3, 4), (0, 2)), 5, 5)  # 28 → 29 ต่างหลักเดียว
    assert not capture.grid_similar(grid, jpeg(moved((3, 4), (0, 2)), 50), 5, 5)
    assert not capture.grid_similar(grid, moved((0, 0), (4, 4)), 5, 5)  # 7 → 10


if __name__ == "__main__":
    test_real_next_box_with_label_and_overlay_line()
    test_real_grid_all_25()
    test_scrcpy_next_box()
    test_scrcpy_grid_sync()
    test_scrcpy_grid_sync_degraded()
    test_grid_similar_ignores_video_noise_but_not_one_changed_cell()
    print("test_real_capture.py OK")
