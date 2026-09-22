"""เทสต์ phonetap (ไม่ต้องมีมือถือ) — รัน: .venv\\Scripts\\python.exe tests\\test_phonetap.py

- parse ผลของ adb / เลือกเครื่อง / ขนาดจอ
- byte ของ INJECT_TOUCH_EVENT เทียบกับค่าอ้างอิงของ scrcpy 4.x (ดู _REF_DOWN)
- handshake + แตะ + หลุดกลางทาง กับ server ปลอมบน localhost ที่ทำตัวเหมือน scrcpy-server (dummy byte →
  ชื่อเครื่อง 64 byte → control)
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phonetap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_parse_devices_and_pick_serial() -> None:
    out = (
        "List of devices attached\n"
        "10AD840MTB00232        device product:V2250T model:V2250 device:V2250 transport_id:1\n"
        "emulator-5554          offline transport_id:2\n"
        "192.168.1.9:5555       device product:x model:Pixel_7 device:y transport_id:3\n"
    )
    devices = phonetap.parse_devices(out)
    assert devices == [("10AD840MTB00232", "V2250"), ("192.168.1.9:5555", "Pixel_7")]
    assert phonetap.pick_serial(devices, "V2250") == "10AD840MTB00232"  # ชื่อหน้าต่าง scrcpy = ชื่อรุ่น
    assert phonetap.pick_serial(devices[:1], "อะไรก็ได้") == "10AD840MTB00232"  # เครื่องเดียวใช้เลย
    try:
        phonetap.pick_serial(devices, "unknown")
        raise AssertionError("ต้องเลือกไม่ได้เมื่อมีหลายเครื่องแต่ชื่อไม่ตรง")
    except phonetap.PhoneTapError:
        pass


def test_parse_wm_size_prefers_override() -> None:
    assert phonetap.parse_wm_size("Physical size: 1260x2800\n") == (1260, 2800)
    assert phonetap.parse_wm_size("Physical size: 1260x2800\nOverride size: 1080x2400\n") == (1080, 2400)


# byte อ้างอิงของ INJECT_TOUCH_EVENT (scrcpy 4.x) ที่ (630, 700) บนจอ 1260×2800 — สร้างจากตัวเข้ารหัสของ
# phone_remote/protocol.py (เทียบ byte กับซอร์ส scrcpy v4.1 แล้ว; โฟลเดอร์นั้นถูกเอาออกจาก repo 2026-09-23
# ดูได้ใน git history commit 054900a) — type 2, action, pointer GENERIC_FINGER (-2), x, y, w, h,
# pressure u16 fixed (DOWN = 0xFFFF, UP = 0), action_button, buttons
_REF_DOWN = bytes.fromhex("0200fffffffffffffffe00000276000002bc04ec0af0ffff0000000000000000")
_REF_UP = bytes.fromhex("0201fffffffffffffffe00000276000002bc04ec0af000000000000000000000")


def test_touch_bytes_match_scrcpy_protocol() -> None:
    assert phonetap.touch_message(phonetap.ACTION_DOWN, 630, 700, 1260, 2800) == _REF_DOWN
    assert phonetap.touch_message(phonetap.ACTION_UP, 630, 700, 1260, 2800) == _REF_UP


class FakeServer:
    """เลียนแบบ scrcpy-server ตอน tunnel_forward=true, video=false: dummy byte + ชื่อเครื่อง แล้วรับ control."""

    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.received = b""
        self.conn = None
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        self.conn, _ = self.listener.accept()
        self.conn.sendall(b"\x00" + b"V2250".ljust(64, b"\x00"))
        try:
            while True:
                chunk = self.conn.recv(4096)
                if not chunk:
                    return
                self.received += chunk
        except OSError:  # drop() ปิด socket ใต้ recv ที่ค้างอยู่
            return

    def drop(self) -> None:
        self.conn.shutdown(socket.SHUT_RDWR)
        self.conn.close()
        self.listener.close()


def test_handshake_tap_and_disconnect() -> None:
    server = FakeServer()
    tapper = phonetap.PhoneTapper(ROOT, "V2250")
    tapper.size = (1260, 2800)
    tapper._sock = tapper._handshake(server.port)
    assert tapper.alive

    tapper.tap(0.5, 0.25, hold_s=0.01)  # กลางจอแนวนอน ค่อนขึ้นบน
    time.sleep(0.2)
    down = phonetap.touch_message(phonetap.ACTION_DOWN, 630, 700, 1260, 2800)
    up = phonetap.touch_message(phonetap.ACTION_UP, 630, 700, 1260, 2800)
    assert server.received == down + up, server.received

    tapper.tap(0.25, 0.5, hold_s=0.0, landscape=True)  # แนวนอน: ขนาดจอสลับเป็น 2800×1260
    time.sleep(0.2)
    assert server.received.endswith(phonetap.touch_message(phonetap.ACTION_UP, 700, 630, 2800, 1260))

    server.drop()  # มือถือหลุด/server ตาย → ต้องรู้ตัว แล้วแตะครั้งต่อไป error ให้ผู้เรียกไปทางสำรอง
    deadline = time.monotonic() + 2
    while tapper.alive and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not tapper.alive
    try:
        tapper.tap(0.5, 0.5)
        raise AssertionError("แตะหลังหลุดต้อง error")
    except phonetap.PhoneTapError:
        pass
    tapper.close()


if __name__ == "__main__":
    test_parse_devices_and_pick_serial()
    test_parse_wm_size_prefers_override()
    test_touch_bytes_match_scrcpy_protocol()
    test_handshake_tap_and_disconnect()
    print("test_phonetap.py OK")
