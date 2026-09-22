"""หาไฟล์ฟอนต์สำหรับวาดภาพตัวเลขในเทสต์ — ชื่อไฟล์ฟอนต์เดียวกันคนละชื่อในแต่ละระบบ

Windows เก็บเป็น arial.ttf / ariblk.ttf ส่วน macOS เก็บเป็น "Arial.ttf" / "Arial Black.ttf" ใน
/System/Library/Fonts/Supplemental (PIL เดินหาในโฟลเดอร์ย่อยให้อยู่แล้ว จึงส่งแค่ชื่อไฟล์ได้)
ต้องเป็นฟอนต์จริงเท่านั้น — ImageFont.load_default() เป็นบิตแมปตัวจิ๋ว Tesseract อ่านไม่ออก เทสต์จะ
ล้มแบบงงๆ แทนที่จะบอกว่าหาฟอนต์ไม่เจอ
"""
from PIL import ImageFont

REGULAR = ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf")
BLACK = ("ariblk.ttf", "Arial Black.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf")


def truetype(names, size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise OSError(f"หาฟอนต์สำหรับเทสต์ไม่เจอ (ลองแล้ว: {', '.join(names)})")
