"""Screen capture + digit OCR.

- capture ใช้ mss (สร้าง instance ใหม่ทุกครั้งที่ grab เพื่อความ thread-safe — เทคนิคเดียวกับ
  bot_detect_word/ocr_engine.py เพราะ mss ไม่ thread-safe ข้าม instance)
- OCR ใช้ pytesseract จำกัดชุดตัวอักษรเป็นตัวเลขล้วน (whitelist) แม่นกว่าอ่านคำทั่วไปมาก
- grab หนึ่งครั้ง ~17ms (= 1 เฟรมจอ 60Hz — DWM รอ vsync ใช้ instance ซ้ำก็ไม่เร็วขึ้น)
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional, Tuple

import mss
import pytesseract
from PIL import Image, ImageChops, ImageFilter, ImageOps

Rect = Tuple[int, int, int, int]
Cell = Tuple[int, int]  # (row, col)

_DIGITS_RE = re.compile(r"\d+")

# OCR หนึ่งครั้ง ~77ms ซึ่งเกือบทั้งหมดคือค่าเปิด process tesseract (preprocess แค่ 0.5ms) — อ่านหลายช่อง
# พร้อมกันจึงเร็วขึ้นเกือบเท่าตัวต่อ worker (วัดจริง 25 ช่อง: ทีละช่อง 1.9s, ขนาน 12 ตัว ~0.3s)
_OCR_WORKERS = 12
_pool: Optional[ThreadPoolExecutor] = None
# tesseract แต่ละ process แตก OpenMP thread เองอีกชั้น — พอรันขนานหลาย process จะแย่ CPU กันเอง
# ให้ process ละ 1 thread แล้วไปขนานกันที่ระดับ process แทน (process ลูกสืบทอด env นี้)
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


def _ocr_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=_OCR_WORKERS, thread_name_prefix="ocr")
    return _pool

# path เริ่มต้นของ Tesseract บน Windows (เหมือน bot_detect_word) — ตั้งให้อัตโนมัติถ้าเจอ
# และผู้ใช้ยังไม่ได้ตั้งเองใน config
_DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def configure_tesseract(explicit_cmd: str = "") -> None:
    if explicit_cmd:
        pytesseract.pytesseract.tesseract_cmd = explicit_cmd
        return
    if os.path.isfile(_DEFAULT_TESSERACT):
        pytesseract.pytesseract.tesseract_cmd = _DEFAULT_TESSERACT
    # ไม่งั้นปล่อยให้ pytesseract หาจาก PATH เอง


def grab(rect: Rect) -> Image.Image:
    """rect = (left, top, width, height) พิกัดจอจริง (physical px) -> PIL.Image (RGB).
    ห้ามส่งพิกัด Qt ตรงๆ — จอที่ scale ≠ 100% จะจับผิดที่ (แปลงผ่าน screenmap.ScreenMap ก่อน)."""
    left, top, w, h = rect
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": max(1, w), "height": max(1, h)})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# พิกเซลที่มืดกว่านี้ (หลัง autocontrast) นับเป็น "หมึก" — เกณฑ์กลาง 150 ใช้ได้ดีกับตัวเลขทึบบนพื้นสว่าง
_INK_THRESHOLD = 150
# ความสูงตัวเลขที่ปรับให้ก่อนส่ง Tesseract (px) — ตัวแรกคือค่าหลัก ที่เหลือใช้ลองซ้ำเมื่ออ่านไม่ออก
# การอัปสเกลตายตัว 4 เท่าแบบเดิมทำให้ตัวเลขฟอนต์หนาของเกมจริงสูง ~150px จน Tesseract อ่านไม่ออก ("8")
# หรืออ่านผิดแบบมั่นใจ (25→29, 27→2) — วัดกับภาพ 576 ภาพ (เกมจริง + Arial/Arial Black 22–56px)
# ขนาดเดียวยังมีบางขนาดฟอนต์ที่ Tesseract สะดุดคืน None แต่พอลองอีกขนาดก็อ่านได้ — ครบ 3 ขนาดนี้ถูกหมด
_DIGIT_HEIGHTS = (40, 32, 52)


def _ink_components(ink: Image.Image) -> List[Tuple[int, int, int, int, bool]]:
    """หา connected component ของพิกเซลหมึก (ภาพโหมด L ค่า 1 = หมึก) แบบ 4-neighbour
    คืน [(x0, y0, x1, y1, แตะขอบภาพไหม)] — ภาพเล็กแค่ระดับเซลล์เดียว วนด้วย Python ล้วนก็ไม่กี่ ms."""
    w, h = ink.size
    data = ink.tobytes()
    seen = bytearray(w * h)
    comps = []
    for start in range(w * h):
        if not data[start] or seen[start]:
            continue
        seen[start] = 1
        stack = [start]
        x0 = x1 = start % w
        y0 = y1 = start // w
        while stack:
            i = stack.pop()
            y, x = divmod(i, w)
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for j, ok in ((i - w, y > 0), (i + w, y < h - 1), (i - 1, x > 0), (i + 1, x < w - 1)):
                if ok and data[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        touches = x0 == 0 or y0 == 0 or x1 == w - 1 or y1 == h - 1
        comps.append((x0, y0, x1, y1, touches))
    return comps


def _crop_to_digits(g: Image.Image) -> Tuple[Image.Image, int]:
    """ตัดภาพ (grayscale ที่ autocontrast แล้ว) ให้เหลือแค่แถวตัวเลขหลัก คืน (ภาพที่ตัด, ความสูงตัวเลข px).

    ทิ้งทุกอย่างที่แตะขอบภาพ (เส้นขอบ overlay ที่ mss จับติดมาด้วย, ขอบการ์ด, เศษเซลล์ข้างๆ) แล้วเก็บเฉพาะ
    ชิ้นที่สูงใกล้เคียงชิ้นที่สูงที่สุดและอยู่บรรทัดเดียวกัน — ตัดป้าย "เลขต่อไป" (ตัวเล็กกว่า) ทิ้งไปด้วย
    ถ้าไม่เหลืออะไรเลย (เช่นตัวเลขชิดขอบกรอบ) คืนภาพเดิมทั้งก้อนแทน."""
    ink = g.point(lambda p: 1 if p <= _INK_THRESHOLD else 0)
    comps = [c for c in _ink_components(ink) if not c[4]]
    if not comps:
        bbox = ink.getbbox()
        return g, (bbox[3] - bbox[1]) if bbox else g.height
    tallest = max(comps, key=lambda c: c[3] - c[1])
    digit_h = tallest[3] - tallest[1] + 1
    line = [
        c for c in comps
        if c[3] - c[1] + 1 >= 0.6 * digit_h and c[1] <= tallest[3] and c[3] >= tallest[1]
    ]
    # เผื่อขอบไว้ ~30% ของความสูงตัวเลข — ตัดชิดขอบหมึกพอดีแล้วขอบ anti-alias ของตัวเลขหายตอน resize
    # (วัดจริง: "27" เหลือ "2")
    pad = max(2, int(digit_h * 0.3))
    x0 = max(0, min(c[0] for c in line) - pad)
    y0 = max(0, min(c[1] for c in line) - pad)
    x1 = min(g.width, max(c[2] for c in line) + pad + 1)
    y1 = min(g.height, max(c[3] for c in line) + pad + 1)
    return g.crop((x0, y0, x1, y1)), digit_h


def _scale_and_binarize(g: Image.Image, digit_h: int, target_h: int) -> Image.Image:
    scale = max(0.5, min(8.0, target_h / max(1, digit_h)))
    g = g.resize((max(1, round(g.width * scale)), max(1, round(g.height * scale))), Image.LANCZOS)
    g = g.point(lambda p: 255 if p > _INK_THRESHOLD else 0)
    # กรอง speckle เล็กๆ ที่เกิดจาก anti-aliasing ตอน resize/threshold — กันไม่ให้ Tesseract
    # (psm 8) เห็นเป็นตัวอักษรปลอมแทรกมา (วัดจริง: เจอเลข "411"/"30" หลอนโผล่มาก่อนใส่ตัวนี้)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    # เว้นขอบขาวรอบตัวเลข — Tesseract ไม่ชอบตัวอักษรชิดขอบภาพ
    return ImageOps.expand(g, border=20, fill=255)


def _preprocess_for_digits(img: Image.Image, target_h: int = _DIGIT_HEIGHTS[0]) -> Image.Image:
    g, digit_h = _crop_to_digits(ImageOps.autocontrast(img.convert("L")))
    return _scale_and_binarize(g, digit_h, target_h)


def read_number(img: Image.Image, psm: int = 6) -> Optional[int]:
    """OCR ภาพที่คาดว่ามีแค่ตัวเลข -> int หรือ None ถ้าอ่านไม่ออก."""
    return _ocr_digits(_preprocess_for_digits(img), psm)


def _ocr_digits(proc: Image.Image, psm: int) -> Optional[int]:
    cfg = f"--psm {psm} -c tessedit_char_whitelist=0123456789"
    try:
        text = pytesseract.image_to_string(proc, config=cfg)
    except Exception:
        return None
    m = _DIGITS_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group())
    except ValueError:
        return None


# (ความสูงตัวเลข px, psm) ตามลำดับที่ลอง — psm 7 (บรรทัดเดียว) ก่อน psm 8: psm 6 อ่านเลข "8" ตัวเดียว
# ฟอนต์หนาไม่ออกเลยทุกขนาด แต่ psm 7 อ่านได้ และในชุดวัด 576 ภาพไม่เคยอ่านผิดแบบมั่นใจเหมือน psm 8
_ATTEMPTS = [(h, 6) for h in _DIGIT_HEIGHTS] + [(_DIGIT_HEIGHTS[0], 7), (_DIGIT_HEIGHTS[0], 8)]


def read_number_robust(
    img: Image.Image, valid_max: Optional[int] = None, parallel: bool = False
) -> Optional[int]:
    """อ่านเลขแบบหลายรอบ — เลือก psm 6 (บล็อกข้อความ) เป็นหลักเพราะพลาดแบบ "คืน None" (ปลอดภัย,
    ไปวนรอบถัดไปแค่นั้น) มากกว่าพลาดแบบ "มั่นใจผิด" — วัดจริงกับเลข 1/11 แล้วพบว่า psm 8 (คำเดี่ยว)
    อ่าน "1" เป็น "4" และ "11" เป็น "411" อย่างมั่นใจ ซึ่งอันตรายกว่ามากเวลาเอาไปจับคู่ตำแหน่งเซลล์
    (ทำให้เซลล์เลข 1 แอบไปทับตำแหน่งเลข 4 ในตาราง) จึงลอง psm 6 ครบทุกขนาดใน `_DIGIT_HEIGHTS` ก่อน
    แล้วค่อย psm 7 และ psm 8 เป็นตัวสำรองสุดท้าย เมื่ออ่านไม่ออก (ว่างเปล่า) *หรือ* อ่านได้เลขที่เกินช่วงที่
    เป็นไปได้จริง (`valid_max`, เช่นเกม 1–25 แต่อ่าน "25" เป็น "29" — ชัดว่าเป็นไปไม่ได้).

    `parallel=True` ยิงทุกรอบพร้อมกันใน pool แล้วเลือกผลตามลำดับเดิม — ผลเหมือนเดิมทุกประการแต่รอแค่
    ~1 ครั้ง OCR (ใช้กับกรอบเลขต่อไปซึ่งอ่านทุกคลิก — เลข "6" ของเกมจริงต้องถึงรอบที่ 2) **ห้ามใช้จาก
    thread ใน pool เอง** (read_cells) — งานย่อยจะรอคิว pool ที่ตัวเองยึดไว้จน deadlock."""

    def _in_range(n: Optional[int]) -> bool:
        if n is None:
            return False
        if valid_max is None:
            return True
        return 1 <= n <= valid_max

    # ตัดหาตัวเลขครั้งเดียว แล้วแค่ย่อ/ขยายต่างขนาดในแต่ละรอบ
    g, digit_h = _crop_to_digits(ImageOps.autocontrast(img.convert("L")))
    attempts = _ATTEMPTS
    if parallel:
        futures = [
            _ocr_pool().submit(_ocr_digits, _scale_and_binarize(g, digit_h, target_h), psm)
            for target_h, psm in attempts
        ]
        results = (f.result() for f in futures)
    else:
        results = (_ocr_digits(_scale_and_binarize(g, digit_h, t), psm) for t, psm in attempts)
    first: Optional[int] = None
    for n in results:
        if _in_range(n):
            return n
        if first is None:
            first = n
    # ไม่มีรอบไหนอยู่ในช่วงเลย — คืนเลขแรกที่อ่านได้ (ดีกว่าไม่มีอะไร) ให้ผู้เรียกตัดสินเอง
    return first


def same_image(a: Image.Image, b: Image.Image) -> bool:
    """ภาพสองภาพเหมือนกันทุกพิกเซลไหม — ใช้ดูว่าจอเปลี่ยนหรือยังก่อนเสีย OCR (~77ms) กับภาพเดิม."""
    return a.size == b.size and ImageChops.difference(a, b).getbbox() is None


# พิกเซลที่ต่างเกิน _SIMILAR_PIXEL_DIFF (หลังเบลอ 1px) เกิน _SIMILAR_CELL_FRACTION ของช่อง = ช่องนั้นเปลี่ยน
# วัดกับภาพ scrcpy จริง: noise JPEG q30 ของภาพเดิม 0.0% ของช่อง, เลขเปลี่ยนจริง ≥ 3.8% (แม้ต่างหลักเดียว 28→29)
# — ห้ามย่อภาพก่อนเทียบ: ย่อเหลือช่องละ 12px แล้ว 7→10 ต่างเฉลี่ยแค่ 3.4 จับไม่ได้
_SIMILAR_PIXEL_DIFF = 40
_SIMILAR_CELL_FRACTION = 0.01


def grid_similar(a: Image.Image, b: Image.Image, rows: int, cols: int) -> bool:
    """ตารางสองภาพเป็นตารางเดียวกันไหม — เทียบทีละช่อง: เลขเปลี่ยนแค่ช่องเดียวต้องจับได้ แต่ noise จาก
    การบีบอัดวิดีโอของ scrcpy ต้องไม่นับ (same_image เทียบทุกพิกเซลเข้มเกินไปสำหรับงานนี้)."""
    if a.size != b.size:
        return False
    blur = ImageFilter.BoxBlur(1)
    diff = ImageChops.difference(a.convert("L").filter(blur), b.convert("L").filter(blur))
    strong = diff.point(lambda p: 255 if p > _SIMILAR_PIXEL_DIFF else 0)
    w, h = a.size
    for r in range(rows):
        for c in range(cols):
            cell = strong.crop((int(c * w / cols), int(r * h / rows), int((c + 1) * w / cols), int((r + 1) * h / rows)))
            if cell.histogram()[255] > _SIMILAR_CELL_FRACTION * cell.width * cell.height:
                return False
    return True


def cell_center(grid_rect: Rect, rows: int, cols: int, cell: Cell) -> Tuple[int, int]:
    """จุดกลางช่อง (row, col) เป็นพิกัดเดียวกับ grid_rect."""
    left, top, w, h = grid_rect
    r, c = cell
    return left + int((c + 0.5) * w / cols), top + int((r + 0.5) * h / rows)


def read_cells(
    grid_rect: Rect,
    rows: int,
    cols: int,
    cells: Optional[Iterable[Cell]] = None,
    cell_pad_ratio: float = 0.16,
    max_number: Optional[int] = None,
) -> Dict[Cell, Optional[int]]:
    """จับภาพ grid_rect ครั้งเดียว แล้ว OCR เฉพาะช่องที่ขอ (None = ทุกช่อง) แบบขนาน
    คืน {(row, col): เลข หรือ None ถ้าอ่านไม่ออก/ช่องว่าง}."""
    crops = _cell_crops(grid_rect, rows, cols, cells, cell_pad_ratio)
    nums = _ocr_pool().map(lambda img: read_number_robust(img, valid_max=max_number), crops.values())
    return dict(zip(crops.keys(), nums))


def read_cells_votes(
    grid_rect: Rect,
    rows: int,
    cols: int,
    cells: Iterable[Cell],
    cell_pad_ratio: float = 0.16,
) -> Dict[Cell, List[Optional[int]]]:
    """เหมือน read_cells แต่อ่านครบทุกรอบใน `_ATTEMPTS` (ไม่หยุดที่รอบแรกที่อ่านได้) แล้วคืนผลทุกรอบต่อช่อง
    ให้ gridsolve นับเสียง — ใช้กับช่องที่ผลรอบแรกขัดกับกติกาเกม. จับภาพใหม่ = ได้เฟรมใหม่อีกตัวอย่าง.
    ยิงทุก (ช่อง, รอบ) เข้า pool พร้อมกัน (~1–2 ครั้ง OCR แทน 5 ครั้งเรียงกัน) — **ห้ามเรียกจาก thread ใน pool**."""
    crops = _cell_crops(grid_rect, rows, cols, cells, cell_pad_ratio)
    futures = {}
    for cell, img in crops.items():
        g, digit_h = _crop_to_digits(ImageOps.autocontrast(img.convert("L")))
        futures[cell] = [
            _ocr_pool().submit(_ocr_digits, _scale_and_binarize(g, digit_h, t), psm) for t, psm in _ATTEMPTS
        ]
    return {cell: [f.result() for f in fs] for cell, fs in futures.items()}


def _cell_crops(
    grid_rect: Rect, rows: int, cols: int, cells: Optional[Iterable[Cell]], cell_pad_ratio: float
) -> Dict[Cell, Image.Image]:
    _, _, w, h = grid_rect
    full = grab(grid_rect)
    cell_w = w / cols
    cell_h = h / rows
    pad_x = cell_w * cell_pad_ratio
    pad_y = cell_h * cell_pad_ratio
    if cells is None:
        cells = [(r, c) for r in range(rows) for c in range(cols)]

    crops: Dict[Cell, Image.Image] = {}
    for r, c in cells:
        cx0 = c * cell_w + pad_x
        cy0 = r * cell_h + pad_y
        cx1 = (c + 1) * cell_w - pad_x
        cy1 = (r + 1) * cell_h - pad_y
        if cx1 <= cx0 or cy1 <= cy0:
            continue
        crops[(r, c)] = full.crop((int(cx0), int(cy0), int(cx1), int(cy1)))
    return crops


def read_grid_numbers(
    grid_rect: Rect,
    rows: int,
    cols: int,
    cell_pad_ratio: float = 0.16,
    max_number: Optional[int] = None,
) -> Dict[int, Tuple[int, int]]:
    """อ่านทั้งตาราง คืน dict {เลข: (center_x, center_y)} เป็นพิกัดเดียวกับ grid_rect (สำหรับคลิก).
    ช่องไหนอ่านไม่ออก/อ่านซ้ำเลขเดิมที่แม่นกว่าอยู่แล้ว จะถูกข้าม.
    """
    result: Dict[int, Tuple[int, int]] = {}
    for cell, num in read_cells(grid_rect, rows, cols, None, cell_pad_ratio, max_number).items():
        if num is None:
            continue
        # ถ้าเลขซ้ำ (OCR หลอน) เก็บอันแรกไว้ก่อน ไม่ต้องเขียนทับ
        result.setdefault(num, cell_center(grid_rect, rows, cols, cell))
    return result
