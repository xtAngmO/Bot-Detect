"""เทสต์ OCR เลขโดดเดียว (จำลองกรอบ 'เลขต่อไป') — รัน: .venv\\Scripts\\python.exe tests\\test_ocr.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont

import capture

capture.configure_tesseract("")


def _digit_image(text: str, size: int = 60) -> Image.Image:
    img = Image.new("RGB", (120, 120), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size)
    except Exception:
        font = ImageFont.load_default()
    d.text((20, 25), text, fill="black", font=font)
    return img


def test_read_number_two_digit() -> None:
    result = capture.read_number_robust(_digit_image("17"))
    assert result == 17, f"expected 17, got {result}"


def test_read_number_single_digit_prone_to_confusion() -> None:
    # "1" เคยโดน psm 8 อ่านเป็น "4" มาก่อน — เทสต์นี้กันการรีเกรส
    result = capture.read_number_robust(_digit_image("1"), valid_max=25)
    assert result == 1, f"expected 1, got {result}"


def _bold_card(text: str, size: int) -> Image.Image:
    """การ์ดฟอนต์หนา (Arial Black) คล้ายเกมจริง — ตัวเลขใหญ่เท่าไหร่ก็ต้องอ่านได้ เพราะ pipeline ปรับความสูง
    ตัวเลขให้คงที่ก่อน OCR (ของเดิมอัปสเกลตายตัว 4 เท่าแล้วอ่าน 25→29, 27→2 แบบมั่นใจผิด)."""
    img = Image.new("RGB", (110, 150), "#e8e8e8")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 106, 146), radius=12, fill="#f4f4f4")
    font = ImageFont.truetype("ariblk.ttf", size)
    b = d.textbbox((0, 0), text, font=font)
    d.text(((110 - (b[2] - b[0])) / 2 - b[0], (150 - (b[3] - b[1])) / 2 - b[1]), text, fill="#2b2b2b", font=font)
    return img


def test_read_number_bold_font_any_size() -> None:
    for n in (1, 8, 11, 17, 25, 27, 35, 47):
        for size in (26, 40):
            result = capture.read_number_robust(_bold_card(str(n), size), valid_max=50)
            assert result == n, f"bold {n} @ {size}px: expected {n}, got {result}"


if __name__ == "__main__":
    test_read_number_two_digit()
    test_read_number_single_digit_prone_to_confusion()
    test_read_number_bold_font_any_size()
    print("test_ocr.py OK")
