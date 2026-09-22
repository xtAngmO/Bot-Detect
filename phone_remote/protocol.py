"""โปรโตคอลระหว่างคอมกับ scrcpy-server v4.1 — แปลงข้อความเป็น byte และอ่าน header ของสตรีม.

ไม่พึ่ง Qt/ซ็อกเก็ตเลย เทสต์ได้ด้วย byte ล้วน ถอดมาจากซอร์ส scrcpy v4.1 ตรงตัว:
- server/.../control/ControlMessageReader.java  (ข้อความ คอม -> มือถือ)
- server/.../control/DeviceMessageWriter.java   (ข้อความ มือถือ -> คอม)
- server/.../device/Streamer.java               (header 12 byte ของวิดีโอ)
- app/tests/test_control_msg_serialize.c        (ตัวอย่าง byte ที่ใช้เทียบใน tests/test_protocol.py)

โปรโตคอลนี้เป็นของภายใน scrcpy — เปลี่ยนได้ทุกเวอร์ชัน และ server จะไม่ยอมรันถ้าเวอร์ชันที่ส่งไป
ไม่ตรงกับตัวมันเอง อัปเดต SCRCPY_VERSION ต้องไล่เทียบไฟล์ข้างบนใหม่ทุกครั้ง
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Union

SCRCPY_VERSION = "4.1"
SERVER_URL = f"https://github.com/Genymobile/scrcpy/releases/download/v{SCRCPY_VERSION}/scrcpy-server-v{SCRCPY_VERSION}"
SERVER_SHA256 = "deacb991ed2509715160ffdc7907e47b4160eb30d1566217e9047fd5b8850cae"
DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"

DEVICE_NAME_LENGTH = 64
CODEC_H264 = 0x68323634  # "h264"

# ---- ชนิดข้อความ คอม -> มือถือ (ControlMessage.TYPE_*) ----
TYPE_INJECT_KEYCODE = 0
TYPE_INJECT_TEXT = 1
TYPE_INJECT_TOUCH_EVENT = 2
TYPE_INJECT_SCROLL_EVENT = 3
TYPE_BACK_OR_SCREEN_ON = 4
TYPE_EXPAND_NOTIFICATION_PANEL = 5
TYPE_EXPAND_SETTINGS_PANEL = 6
TYPE_COLLAPSE_PANELS = 7
TYPE_GET_CLIPBOARD = 8
TYPE_SET_CLIPBOARD = 9
TYPE_SET_DISPLAY_POWER = 10
TYPE_ROTATE_DEVICE = 11
TYPE_RESET_VIDEO = 17

# ---- ชนิดข้อความ มือถือ -> คอม (DeviceMessage.TYPE_*) ----
DEVICE_MSG_CLIPBOARD = 0
DEVICE_MSG_ACK_CLIPBOARD = 1
DEVICE_MSG_UHID_OUTPUT = 2

# ---- ค่าคงที่ของ Android ----
ACTION_DOWN = 0  # ใช้ร่วมทั้ง KeyEvent และ MotionEvent
ACTION_UP = 1
ACTION_MOVE = 2  # MotionEvent เท่านั้น

# pointer id พิเศษของ scrcpy: GENERIC_FINGER ทำให้ server ฉีดเป็น "นิ้วแตะจอ" (SOURCE_TOUCHSCREEN)
# เสมอ — เกม/แอปบางตัวไม่รับ event ที่มาจากเมาส์ จึงใช้ตัวนี้กับคลิกซ้ายทั้งหมด
POINTER_ID_MOUSE = -1
POINTER_ID_GENERIC_FINGER = -2
POINTER_ID_VIRTUAL_FINGER = -3  # นิ้วที่สองของท่าถ่างซูม (Ctrl+ลาก)

INJECT_TEXT_MAX_BYTES = 300  # ControlMessageReader.INJECT_TEXT_MAX_LENGTH
CLIPBOARD_TEXT_MAX_BYTES = (1 << 18) - 14

_U64 = 0xFFFF_FFFF_FFFF_FFFF


def _u16_fixed(value: float) -> int:
    """float [0, 1] -> u16 fixed point (sc_float_to_u16fp): 1.0 ต้องได้ 0xffff ไม่ใช่ 0x10000."""
    value = min(max(value, 0.0), 1.0)
    return 0xFFFF if value >= 1.0 else int(value * 0x10000)


def _i16_fixed(value: float) -> int:
    """float [-1, 1] -> i16 fixed point (sc_float_to_i16fp): 1.0 ตันที่ 0x7fff."""
    value = min(max(value, -1.0), 1.0)
    return min(int(value * 0x8000), 0x7FFF)


def _utf8_truncate(text: str, max_bytes: int) -> bytes:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return raw
    # ตัดไม่ให้ขาดกลางตัวอักษร UTF-8 (byte ต่อเนื่องขึ้นต้นด้วย 10xxxxxx)
    cut = max_bytes
    while cut > 0 and (raw[cut] & 0xC0) == 0x80:
        cut -= 1
    return raw[:cut]


# ---------------------------------------------------------------- คอม -> มือถือ

def inject_keycode(action: int, keycode: int, repeat: int = 0, meta_state: int = 0) -> bytes:
    return struct.pack(">BBiii", TYPE_INJECT_KEYCODE, action, keycode, repeat, meta_state)


def inject_text(text: str) -> bytes:
    """พิมพ์ข้อความตรง ๆ — server แปลงผ่าน KeyCharacterMap จึงได้แค่ตัวอักษรที่คีย์บอร์ดจริงพิมพ์ได้
    (ภาษาอังกฤษ/ตัวเลข/สัญลักษณ์) ภาษาไทยให้ใช้ set_clipboard(..., paste=True) แทน."""
    raw = _utf8_truncate(text, INJECT_TEXT_MAX_BYTES)
    return struct.pack(">BI", TYPE_INJECT_TEXT, len(raw)) + raw


def inject_touch(action: int, pointer_id: int, x: int, y: int, width: int, height: int,
                 pressure: float = 1.0, action_button: int = 0, buttons: int = 0) -> bytes:
    """(width, height) ต้องเท่ากับขนาดวิดีโอปัจจุบันเป๊ะ ไม่งั้น server ทิ้ง event เงียบ ๆ
    (PositionMapper.map — กันกดผิดที่ตอนมือถือเพิ่งหมุนจอ)."""
    return struct.pack(">BBQiiHHHii", TYPE_INJECT_TOUCH_EVENT, action, pointer_id & _U64,
                       x, y, width, height, _u16_fixed(pressure), action_button, buttons)


def inject_scroll(x: int, y: int, width: int, height: int, hscroll: float, vscroll: float,
                  buttons: int = 0) -> bytes:
    """hscroll/vscroll อยู่ในช่วง [-16, 16] (หน่วยเดียวกับ AXIS_HSCROLL/VSCROLL — 1 = หนึ่งคลิกล้อ)."""
    return struct.pack(">BiiHHhhi", TYPE_INJECT_SCROLL_EVENT, x, y, width, height,
                       _i16_fixed(hscroll / 16), _i16_fixed(vscroll / 16), buttons)


def back_or_screen_on(action: int) -> bytes:
    """ปุ่มย้อนกลับ — ถ้าจอมือถือดับอยู่ server จะเปิดจอแทน (ต้องส่งทั้ง DOWN และ UP)."""
    return struct.pack(">BB", TYPE_BACK_OR_SCREEN_ON, action)


def simple(msg_type: int) -> bytes:
    """ข้อความที่ไม่มี payload: แผงแจ้งเตือน, แผงตั้งค่าด่วน, ปิดแผง, หมุนจอ, reset video."""
    return struct.pack(">B", msg_type)


def get_clipboard(copy_key: int = 0) -> bytes:
    return struct.pack(">BB", TYPE_GET_CLIPBOARD, copy_key)


def set_clipboard(sequence: int, text: str, paste: bool) -> bytes:
    raw = _utf8_truncate(text, CLIPBOARD_TEXT_MAX_BYTES)
    return struct.pack(">BQBI", TYPE_SET_CLIPBOARD, sequence & _U64, 1 if paste else 0, len(raw)) + raw


def set_display_power(on: bool) -> bytes:
    """ปิด/เปิดจอจริงของมือถือ โดยภาพบนคอมยังเล่นต่อ (เหมือน scrcpy Alt+O)."""
    return struct.pack(">BB", TYPE_SET_DISPLAY_POWER, 1 if on else 0)


# ---------------------------------------------------------------- สตรีมวิดีโอ (มือถือ -> คอม)

_FLAG_SESSION = 1 << 63
_FLAG_CONFIG = 1 << 62
_FLAG_KEY_FRAME = 1 << 61
_PTS_MASK = _FLAG_KEY_FRAME - 1


@dataclass(frozen=True)
class SessionHeader:
    """เริ่ม capture session ใหม่ (ครั้งแรก และทุกครั้งที่มือถือหมุนจอ/พับจอ) — ขนาดวิดีโอเปลี่ยนได้."""
    width: int
    height: int
    client_resized: bool


@dataclass(frozen=True)
class MediaHeader:
    size: int
    pts: int
    config: bool  # SPS/PPS — ต้องเอาไปต่อหน้าแพ็กเก็ตถัดไปก่อนถอดรหัส
    key_frame: bool


def parse_video_header(header: bytes) -> Union[SessionHeader, MediaHeader]:
    """แยก header 12 byte: bit บนสุดเป็น 1 = session packet, 0 = media packet."""
    if len(header) != 12:
        raise ValueError(f"video header must be 12 bytes, got {len(header)}")
    first, size = struct.unpack(">QI", header)
    if first & _FLAG_SESSION:
        flags, width, height = struct.unpack(">III", header)
        return SessionHeader(width=width, height=height, client_resized=bool(flags & 1))
    config = bool(first & _FLAG_CONFIG)
    return MediaHeader(size=size, pts=0 if config else first & _PTS_MASK, config=config,
                       key_frame=bool(first & _FLAG_KEY_FRAME))


def parse_device_name(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


# ---------------------------------------------------------------- ข้อความ มือถือ -> คอม

@dataclass(frozen=True)
class ClipboardMessage:
    text: str


@dataclass(frozen=True)
class AckClipboardMessage:
    sequence: int


@dataclass(frozen=True)
class UhidOutputMessage:
    id: int
    data: bytes


DeviceMessage = Union[ClipboardMessage, AckClipboardMessage, UhidOutputMessage]


def read_device_message(recv_exact: Callable[[int], bytes]) -> DeviceMessage:
    """อ่านข้อความหนึ่งก้อนจาก control socket — recv_exact(n) ต้องคืนครบ n byte หรือ raise."""
    (msg_type,) = struct.unpack(">B", recv_exact(1))
    if msg_type == DEVICE_MSG_CLIPBOARD:
        (length,) = struct.unpack(">I", recv_exact(4))
        return ClipboardMessage(recv_exact(length).decode("utf-8", errors="replace"))
    if msg_type == DEVICE_MSG_ACK_CLIPBOARD:
        (sequence,) = struct.unpack(">Q", recv_exact(8))
        return AckClipboardMessage(sequence)
    if msg_type == DEVICE_MSG_UHID_OUTPUT:
        uhid_id, length = struct.unpack(">HH", recv_exact(4))
        return UhidOutputMessage(uhid_id, recv_exact(length))
    raise ValueError(f"unknown device message type {msg_type}")
