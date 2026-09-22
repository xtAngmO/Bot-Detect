"""เทสต์ตรรกะ UI ที่ไม่ต้องมีจอจริง: การ map พิกัดเมาส์->วิดีโอ, การเลือก keycode, ไอคอน.
รัน:  QT_QPA_PLATFORM=offscreen python tests/test_ui.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import icons
import keymap
from PySide6.QtCore import Qt
from window import fit_rect, map_to_video

_app = QApplication.instance() or QApplication(sys.argv)


def test_fit_rect_keeps_aspect_ratio() -> None:
    # วิดีโอแนวตั้ง 9:19 ในกรอบจัตุรัส -> ต้องเต็มความสูง กว้างตามสัดส่วน วางกลาง
    r = fit_rect(QSize(1000, 1000), QSize(900, 1900))
    assert r.height() == 1000
    assert r.width() == round(900 / 1900 * 1000)
    assert r.x() == (1000 - r.width()) // 2
    assert r.y() == 0


def test_fit_rect_empty_when_no_video() -> None:
    assert fit_rect(QSize(100, 100), QSize(0, 0)).isEmpty()
    assert fit_rect(QSize(0, 0), QSize(100, 100)).isEmpty()


def test_map_to_video_corners_and_outside() -> None:
    rect = fit_rect(QSize(360, 800), QSize(360, 800))  # 1:1
    assert map_to_video(QPoint(0, 0), rect, QSize(360, 800)) == QPoint(0, 0)
    # มุมขวาล่างต้องไม่หลุดขอบ (clamp เป็น w-1, h-1)
    corner = map_to_video(QPoint(359, 799), rect, QSize(360, 800))
    assert corner == QPoint(359, 799)
    # คลิกนอกภาพ -> None
    assert map_to_video(QPoint(-5, 10), rect, QSize(360, 800)) is None


def test_map_to_video_scales_when_downscaled() -> None:
    # widget 180x400 แสดงวิดีโอ 360x800 -> จุดกลาง widget = จุดกลางวิดีโอ
    rect = fit_rect(QSize(180, 400), QSize(360, 800))
    p = map_to_video(QPoint(90, 200), rect, QSize(360, 800))
    assert abs(p.x() - 180) <= 1 and abs(p.y() - 400) <= 1


def test_keycode_special_and_ctrl_letters() -> None:
    assert keymap.keycode_for(Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier) == keymap.KEYCODE_BACK
    assert keymap.keycode_for(Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier) == keymap.KEYCODE_ENTER
    assert keymap.keycode_for(Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier) == keymap.KEYCODE_DPAD_UP
    # Ctrl+A -> keycode A (คีย์ลัด) แต่ A เฉย ๆ -> None (ให้ส่งเป็นข้อความ)
    assert keymap.keycode_for(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier) == keymap.KEYCODE_A
    assert keymap.keycode_for(Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier) is None


def test_meta_state_flags() -> None:
    both = keymap.meta_state(Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
    assert both & keymap.META_SHIFT_ON and both & keymap.META_CTRL_ON


def test_is_injectable_text() -> None:
    assert keymap.is_injectable_text("hello123!") is True
    assert keymap.is_injectable_text("สวัสดี") is False  # ภาษาไทย -> ต้องไปทาง clipboard
    assert keymap.is_injectable_text("") is False


def test_all_icons_render_nonempty() -> None:
    for name in icons.NAMES:
        pm = icons.icon(name).pixmap(QSize(24, 24))
        assert not pm.isNull(), f"ไอคอน {name} วาดไม่ออก"


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("test_ui.py OK")


if __name__ == "__main__":
    _run_all()
