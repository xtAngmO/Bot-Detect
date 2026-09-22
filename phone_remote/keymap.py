"""แปลงคีย์บอร์ดคอม (Qt) เป็น Android keycode/meta state.

แนวทางเดียวกับ scrcpy โหมด --keyboard=sdk:
- ปุ่มพิเศษ (Enter, Backspace, ลูกศร, ...) และคีย์ลัด Ctrl+ตัวอักษร -> ส่งเป็น keycode (กดค้าง/ปล่อยได้)
- ตัวอักษรที่พิมพ์ทั่วไป -> ส่งเป็นข้อความ (inject_text) ไม่ส่งเป็น keycode เพราะ layout คีย์บอร์ดของ
  คอมกับมือถืออาจไม่ตรงกัน
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt

# android.view.KeyEvent.KEYCODE_*
KEYCODE_HOME = 3
KEYCODE_BACK = 4
KEYCODE_DPAD_UP = 19
KEYCODE_DPAD_DOWN = 20
KEYCODE_DPAD_LEFT = 21
KEYCODE_DPAD_RIGHT = 22
KEYCODE_VOLUME_UP = 24
KEYCODE_VOLUME_DOWN = 25
KEYCODE_POWER = 26
KEYCODE_A = 29
KEYCODE_TAB = 61
KEYCODE_SPACE = 62
KEYCODE_ENTER = 66
KEYCODE_DEL = 67  # Backspace
KEYCODE_MENU = 82
KEYCODE_PAGE_UP = 92
KEYCODE_PAGE_DOWN = 93
KEYCODE_FORWARD_DEL = 112
KEYCODE_MOVE_HOME = 122
KEYCODE_MOVE_END = 123
KEYCODE_APP_SWITCH = 187

# android.view.KeyEvent.META_*
META_SHIFT_ON = 0x1
META_ALT_ON = 0x2
META_SHIFT_LEFT_ON = 0x40
META_ALT_LEFT_ON = 0x10
META_CTRL_ON = 0x1000
META_CTRL_LEFT_ON = 0x2000

_SPECIAL = {
    Qt.Key.Key_Return: KEYCODE_ENTER,
    Qt.Key.Key_Enter: KEYCODE_ENTER,
    Qt.Key.Key_Backspace: KEYCODE_DEL,
    Qt.Key.Key_Delete: KEYCODE_FORWARD_DEL,
    Qt.Key.Key_Tab: KEYCODE_TAB,
    Qt.Key.Key_Escape: KEYCODE_BACK,  # Esc = ย้อนกลับ ตามที่คนคุมมือถือคาดหวัง
    Qt.Key.Key_Up: KEYCODE_DPAD_UP,
    Qt.Key.Key_Down: KEYCODE_DPAD_DOWN,
    Qt.Key.Key_Left: KEYCODE_DPAD_LEFT,
    Qt.Key.Key_Right: KEYCODE_DPAD_RIGHT,
    Qt.Key.Key_Home: KEYCODE_MOVE_HOME,
    Qt.Key.Key_End: KEYCODE_MOVE_END,
    Qt.Key.Key_PageUp: KEYCODE_PAGE_UP,
    Qt.Key.Key_PageDown: KEYCODE_PAGE_DOWN,
    Qt.Key.Key_Menu: KEYCODE_MENU,
}


def meta_state(modifiers: Qt.KeyboardModifier) -> int:
    meta = 0
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        meta |= META_SHIFT_ON | META_SHIFT_LEFT_ON
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        meta |= META_CTRL_ON | META_CTRL_LEFT_ON
    if modifiers & Qt.KeyboardModifier.AltModifier:
        meta |= META_ALT_ON | META_ALT_LEFT_ON
    return meta


def keycode_for(key: int, modifiers: Qt.KeyboardModifier) -> Optional[int]:
    """คืน Android keycode ถ้าคีย์นี้ต้องส่งเป็น keycode; None = ให้ส่งเป็นข้อความ (ถ้ามี) แทน."""
    if key in _SPECIAL:
        return _SPECIAL[key]
    # Ctrl+ตัวอักษร (Ctrl+A/C/X/Z ...) ต้องเป็น keycode + META_CTRL ไม่งั้นแอปไม่รู้ว่าเป็นคีย์ลัด
    if modifiers & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return KEYCODE_A + (key - Qt.Key.Key_A)
    return None


def is_injectable_text(text: str) -> bool:
    """inject_text ของ scrcpy ส่งได้แค่ตัวที่ KeyCharacterMap ของ Android พิมพ์ได้ (ASCII ที่พิมพ์ได้)
    ภาษาไทย/อีโมจิ ต้องส่งผ่าน clipboard แล้ววางแทน."""
    return bool(text) and all(" " <= ch <= "~" for ch in text)
