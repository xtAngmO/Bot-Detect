"""เทสต์ end-to-end กับมือถือ/emulator จริง — ต้องมีอุปกรณ์ต่ออยู่ (adb devices เห็น).

ทำจริงทั้งชุด: push scrcpy-server -> เปิด session -> ถอดวิดีโอได้จริง -> ยิงคำสั่งแตะ/คีย์ ->
ปิด session สะอาด (server ลบ jar ตัวเองทิ้ง). ข้ามอัตโนมัติถ้าไม่มีอุปกรณ์ (จะได้ไม่พังใน CI ที่ไม่มีมือถือ)

รัน:  python tests/test_integration.py [serial]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import av

import protocol
from adb import Adb, AdbError
from scrcpy_server import ScrcpySession, StreamOptions, recv_exact


def _pick_device(adb: Adb) -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    ready = [d for d in adb.devices() if d.state == "device"]
    return ready[0].serial if ready else ""


def main() -> int:
    try:
        adb = Adb()
    except AdbError as e:
        print(f"ข้าม test_integration: {e}")
        return 0
    serial = _pick_device(adb)
    if not serial:
        print("ข้าม test_integration: ไม่มีมือถือ/emulator ต่ออยู่ (adb devices ว่าง)")
        return 0

    print(f"ทดสอบกับ {serial}")
    session = ScrcpySession(adb, serial, StreamOptions(max_size=800, max_fps=30)).start(log=print)
    try:
        assert session.device_name, "ไม่ได้ชื่อเครื่องจาก server"
        assert session.video_sock is not None and session.control_sock is not None

        decoder = av.CodecContext.create("h264", "r")
        config = None
        decoded = 0
        width = height = 0
        deadline = time.time() + 15
        while decoded < 3 and time.time() < deadline:
            header = protocol.parse_video_header(recv_exact(session.video_sock, 12))
            if isinstance(header, protocol.SessionHeader):
                width, height = header.width, header.height
                config = None
                continue
            data = recv_exact(session.video_sock, header.size)
            if header.config:
                config = data
                continue
            if config is not None:
                data, config = config + data, None
            packet = av.Packet(data)
            for frame in decoder.decode(packet):
                assert frame.width > 0 and frame.height > 0
                decoded += 1
        assert decoded >= 3, f"ถอดวิดีโอได้แค่ {decoded} เฟรมใน 15 วินาที"
        assert width > 0 and height > 0, "ไม่ได้รับ session header (ขนาดวิดีโอ)"
        print(f"ถอดวิดีโอได้ {decoded} เฟรม ที่ {width}x{height}")

        # ยิงคำสั่งควบคุมจริง — ถ้า socket ยังดีจะส่งครบไม่ error
        cx, cy = width // 2, height // 2
        assert session.control_sock.send(
            protocol.inject_touch(protocol.ACTION_DOWN, protocol.POINTER_ID_GENERIC_FINGER,
                                  cx, cy, width, height)) > 0
        session.control_sock.sendall(
            protocol.inject_touch(protocol.ACTION_UP, protocol.POINTER_ID_GENERIC_FINGER,
                                  cx, cy, width, height))
        session.control_sock.sendall(protocol.inject_keycode(protocol.ACTION_DOWN, 3))  # HOME
        session.control_sock.sendall(protocol.inject_keycode(protocol.ACTION_UP, 3))
        print("ส่งคำสั่งแตะ+HOME สำเร็จ")
    finally:
        session.close()

    # ปิดแล้ว server ต้องลบ jar ตัวเองทิ้ง (cleanup) — ยืนยันว่าไม่ทิ้งขยะไว้บนมือถือ
    time.sleep(1.0)
    listing = adb.shell(serial, f"ls {protocol.DEVICE_SERVER_PATH} 2>/dev/null || echo GONE")
    assert "GONE" in listing or "No such file" in listing, f"scrcpy-server ค้างบนมือถือ: {listing}"
    print("test_integration.py OK — server cleanup เรียบร้อย")
    return 0


if __name__ == "__main__":
    sys.exit(main())
