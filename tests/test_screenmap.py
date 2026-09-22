"""เทสต์แปลงพิกัด logical <-> physical — รัน: .venv\\Scripts\\python.exe tests\\test_screenmap.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screenmap import ScreenMap


def test_identity_at_100_percent() -> None:
    m = ScreenMap()
    assert m.to_physical((683, 215, 117, 125)) == (683, 215, 117, 125)
    assert m.point_to_logical(700, 300) == (700, 300)


def test_scale_125_primary_screen() -> None:
    # ค่าจริงจาก config.json ของผู้ใช้ (จอ 2560×1600 scale 125%) — กรอบที่เห็นบนจออยู่ที่ ×1.25
    m = ScreenMap(0, 0, 1.25)
    assert m.to_physical((683, 215, 117, 125)) == (854, 269, 146, 156)
    assert m.to_physical((419, 322, 433, 786)) == (524, 402, 541, 983)
    assert m.point_to_logical(854, 269) == (683, 215)


def test_secondary_screen_keeps_origin() -> None:
    # จอที่สองเริ่มที่ x=2560 — Qt คงมุมซ้ายบนของจอไว้เท่าเดิม แล้ว scale แค่ส่วนที่อยู่ในจอ
    m = ScreenMap(2560, 0, 1.5)
    assert m.to_physical((2560, 0, 100, 100)) == (2560, 0, 150, 150)
    assert m.to_physical((2660, 100, 10, 10)) == (2710, 150, 15, 15)
    assert m.point_to_logical(2710, 150) == (2660, 100)


if __name__ == "__main__":
    test_identity_at_100_percent()
    test_scale_125_primary_screen()
    test_secondary_screen_keeps_origin()
    print("test_screenmap.py OK")
