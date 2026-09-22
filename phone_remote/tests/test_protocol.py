"""เทียบ byte ที่ protocol.py สร้าง กับค่าที่ scrcpy v4.1 คาดหวังเป๊ะ ๆ.

ค่าที่คาดหวังลอกจาก app/tests/test_control_msg_serialize.c ของ scrcpy โดยตรง — ถ้าอัปเวอร์ชัน
scrcpy แล้วเทสต์นี้แดง แปลว่าโปรโตคอลเปลี่ยน ต้องไล่แก้ protocol.py ตามซอร์สใหม่
รัน:  python tests/test_protocol.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol


def test_inject_keycode_matches_scrcpy() -> None:
    # action=UP, keycode=ENTER(0x42), repeat=5, meta=SHIFT_ON|SHIFT_LEFT_ON(0x41)
    got = protocol.inject_keycode(protocol.ACTION_UP, 0x42, 5, 0x41)
    assert got == bytes([0, 1, 0, 0, 0, 0x42, 0, 0, 0, 5, 0, 0, 0, 0x41])
    assert len(got) == 14


def test_inject_text_matches_scrcpy() -> None:
    got = protocol.inject_text("hello, world!")
    assert got == bytes([1, 0, 0, 0, 0x0D]) + b"hello, world!"
    assert len(got) == 18


def test_inject_text_truncates_on_utf8_boundary() -> None:
    # "อ" = 3 byte ใน UTF-8 — ตัดที่ max 4 byte ต้องได้ 1 ตัว (3 byte) ไม่ใช่ตัดกลางตัวอักษร
    payload = protocol.inject_text("ออ")[5:]  # ตัด header (type + len 4 byte)
    original = protocol.INJECT_TEXT_MAX_BYTES
    try:
        protocol.INJECT_TEXT_MAX_BYTES = 4
        raw = protocol.inject_text("ออ")
        length = struct.unpack(">I", raw[1:5])[0]
        assert length == 3, f"ควรตัดเหลือ 1 ตัวอักษร (3 byte) ได้ {length}"
        assert raw[5:].decode("utf-8") == "อ"
    finally:
        protocol.INJECT_TEXT_MAX_BYTES = original
    assert payload == "ออ".encode("utf-8")


def test_inject_touch_matches_scrcpy() -> None:
    got = protocol.inject_touch(protocol.ACTION_DOWN, 0x1234567887654321, 100, 200, 1080, 1920,
                                pressure=1.0, action_button=1, buttons=1)
    expected = bytes([
        2, 0,
        0x12, 0x34, 0x56, 0x78, 0x87, 0x65, 0x43, 0x21,  # pointer id
        0x00, 0x00, 0x00, 0x64, 0x00, 0x00, 0x00, 0xC8,  # 100 200
        0x04, 0x38, 0x07, 0x80,  # 1080 1920
        0xFF, 0xFF,  # pressure 1.0
        0x00, 0x00, 0x00, 0x01,  # action button
        0x00, 0x00, 0x00, 0x01,  # buttons
    ])
    assert got == expected
    assert len(got) == 32


def test_inject_scroll_matches_scrcpy() -> None:
    got = protocol.inject_scroll(260, 1026, 1080, 1920, hscroll=16, vscroll=-16, buttons=1)
    expected = bytes([
        3,
        0x00, 0x00, 0x01, 0x04, 0x00, 0x00, 0x04, 0x02,  # 260 1026
        0x04, 0x38, 0x07, 0x80,  # 1080 1920
        0x7F, 0xFF,  # +16 (ตันบวก)
        0x80, 0x00,  # -16 (ตันลบ)
        0x00, 0x00, 0x00, 0x01,
    ])
    assert got == expected
    assert len(got) == 21


def test_back_and_simple_messages() -> None:
    assert protocol.back_or_screen_on(protocol.ACTION_UP) == bytes([4, 1])
    assert protocol.simple(protocol.TYPE_EXPAND_NOTIFICATION_PANEL) == bytes([5])
    assert protocol.set_display_power(False) == bytes([10, 0])
    assert protocol.set_display_power(True) == bytes([10, 1])


def test_set_clipboard_layout() -> None:
    got = protocol.set_clipboard(0x0102030405060708, "hi", paste=True)
    assert got[0] == protocol.TYPE_SET_CLIPBOARD
    assert got[1:9] == bytes([1, 2, 3, 4, 5, 6, 7, 8])  # sequence u64
    assert got[9] == 1  # paste flag
    assert struct.unpack(">I", got[10:14])[0] == 2
    assert got[14:] == b"hi"


def test_pressure_full_range_is_0xffff_not_overflow() -> None:
    raw = protocol.inject_touch(protocol.ACTION_DOWN, protocol.POINTER_ID_GENERIC_FINGER,
                                0, 0, 100, 100, pressure=1.0)
    assert raw[22:24] == b"\xff\xff"  # 1.0 ต้องได้ 0xffff ไม่ใช่ 0x0000 จากการ overflow


def test_generic_finger_pointer_id_is_unsigned_encoded() -> None:
    raw = protocol.inject_touch(protocol.ACTION_DOWN, protocol.POINTER_ID_GENERIC_FINGER, 5, 6, 100, 100)
    # -2 -> 0xFFFFFFFFFFFFFFFE
    assert raw[2:10] == b"\xff\xff\xff\xff\xff\xff\xff\xfe"


def test_parse_session_header() -> None:
    header = struct.pack(">III", 0x80000000, 1080, 2400)
    result = protocol.parse_video_header(header)
    assert isinstance(result, protocol.SessionHeader)
    assert (result.width, result.height, result.client_resized) == (1080, 2400, False)

    resized = struct.pack(">III", 0x80000001, 720, 1600)
    r2 = protocol.parse_video_header(resized)
    assert isinstance(r2, protocol.SessionHeader) and r2.client_resized is True


def test_parse_media_headers() -> None:
    config = protocol.parse_video_header(struct.pack(">QI", 1 << 62, 40))
    assert isinstance(config, protocol.MediaHeader)
    assert config.config is True and config.size == 40 and config.pts == 0

    key = protocol.parse_video_header(struct.pack(">QI", (1 << 61) | 123456, 999))
    assert isinstance(key, protocol.MediaHeader)
    assert key.key_frame is True and key.config is False
    assert key.pts == 123456 and key.size == 999

    normal = protocol.parse_video_header(struct.pack(">QI", 777, 10))
    assert normal.key_frame is False and normal.config is False and normal.pts == 777


def test_parse_device_name_strips_padding() -> None:
    raw = b"Pixel 7" + b"\x00" * (protocol.DEVICE_NAME_LENGTH - 7)
    assert protocol.parse_device_name(raw) == "Pixel 7"


def _reader(data: bytes):
    box = {"i": 0}

    def recv(n: int) -> bytes:
        chunk = data[box["i"]:box["i"] + n]
        box["i"] += n
        if len(chunk) != n:
            raise ConnectionError("short read")
        return chunk

    return recv


def test_read_device_clipboard_message() -> None:
    text = "คัดลอกไทย"
    raw_text = text.encode("utf-8")
    data = bytes([protocol.DEVICE_MSG_CLIPBOARD]) + struct.pack(">I", len(raw_text)) + raw_text
    msg = protocol.read_device_message(_reader(data))
    assert isinstance(msg, protocol.ClipboardMessage) and msg.text == text


def test_read_device_ack_and_uhid() -> None:
    ack = bytes([protocol.DEVICE_MSG_ACK_CLIPBOARD]) + struct.pack(">Q", 42)
    m1 = protocol.read_device_message(_reader(ack))
    assert isinstance(m1, protocol.AckClipboardMessage) and m1.sequence == 42

    uhid = bytes([protocol.DEVICE_MSG_UHID_OUTPUT]) + struct.pack(">HH", 7, 3) + b"abc"
    m2 = protocol.read_device_message(_reader(uhid))
    assert isinstance(m2, protocol.UhidOutputMessage) and m2.id == 7 and m2.data == b"abc"


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("test_protocol.py OK")


if __name__ == "__main__":
    _run_all()
