"""thread รับวิดีโอ + ช่องส่งคำสั่งควบคุม — ตัวกลางระหว่าง socket ของ ScrcpySession กับหน้าต่าง Qt.

วิดีโอ: อ่านแพ็กเก็ต -> ถอด H.264 ด้วย PyAV -> ย่อเป็นขนาดที่หน้าต่างแสดงจริง (swscale ใน thread นี้
ถูกกว่าให้ QPainter ย่อภาพเต็มจอบน GUI thread มาก) -> ส่งให้ GUI เฉพาะ "เฟรมล่าสุด" เท่านั้น
ถ้า GUI วาดไม่ทันจะข้ามเฟรมเก่าทิ้ง แทนที่จะต่อคิวจนภาพหน่วงสะสม (สำคัญมากตอนต่อข้ามอินเทอร์เน็ต)
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Optional, Tuple

import av
from av.codec.context import Flags as CodecFlags
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

import protocol
from scrcpy_server import recv_exact


def frame_to_qimage(frame: "av.VideoFrame", width: int = 0, height: int = 0) -> QImage:
    """แปลงเฟรม (yuv420p) เป็น QImage RGB888 — width/height = 0 คือขนาดเดิม."""
    rgb = frame.reformat(width=width or None, height=height or None, format="rgb24",
                         interpolation="BILINEAR" if width else None)
    plane = rgb.planes[0]
    # plane มี padding ท้ายบรรทัด (line_size > width*3) — บอก bytesPerLine ให้ QImage ตรง ๆ
    # แล้ว copy() เพื่อให้ QImage เป็นเจ้าของหน่วยความจำเอง ไม่ผูกกับ buffer ของ PyAV
    return QImage(bytes(plane), rgb.width, rgb.height, plane.line_size, QImage.Format.Format_RGB888).copy()


class VideoReceiver(QThread):
    session_changed = Signal(int, int)  # ขนาดวิดีโอใหม่ (ครั้งแรก + ทุกครั้งที่มือถือหมุนจอ)
    frame_ready = Signal()  # มีเฟรมใหม่ให้ดึงด้วย take_frame()
    stopped = Signal(str)  # จบสตรีม — ข้อความว่างถ้าเราปิดเอง

    def __init__(self, sock: socket.socket, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._sock = sock
        self._lock = threading.Lock()
        self._latest: Optional[QImage] = None
        self._pending = False
        self._target: Tuple[int, int] = (0, 0)
        self._last_frame = None
        self._closing = False
        self.fps = 0.0
        self._fps_count = 0
        self._fps_since = time.monotonic()

    # ---- เรียกจาก GUI thread ----
    def set_target_size(self, width: int, height: int) -> None:
        self._target = (max(1, width), max(1, height))

    def take_frame(self) -> Optional[QImage]:
        with self._lock:
            image, self._latest, self._pending = self._latest, None, False
            return image

    def full_resolution_image(self) -> Optional[QImage]:
        """ภาพเต็มความละเอียดของวิดีโอ (สำหรับปุ่มแคปจอ)."""
        with self._lock:
            frame = self._last_frame
        return frame_to_qimage(frame) if frame is not None else None

    def stop(self) -> None:
        self._closing = True

    # ---- thread ----
    def run(self) -> None:
        reason = ""
        try:
            self._loop()
        except (ConnectionError, OSError) as e:
            reason = "" if self._closing else f"การเชื่อมต่อหลุด: {e}"
        except Exception as e:  # ถอดรหัสพังแบบไม่คาดคิด — แจ้งผู้ใช้แทนการตายเงียบ
            reason = "" if self._closing else f"สตรีมวิดีโอผิดพลาด: {e!r}"
        self.stopped.emit(reason)

    def _new_decoder(self) -> "av.CodecContext":
        codec = av.CodecContext.create("h264", "r")
        codec.flags |= CodecFlags.low_delay  # ไม่ให้ decoder กักเฟรมไว้รอเรียงลำดับ
        return codec

    def _loop(self) -> None:
        codec = self._new_decoder()
        config: Optional[bytes] = None
        while True:
            header = protocol.parse_video_header(recv_exact(self._sock, 12))
            if isinstance(header, protocol.SessionHeader):
                # หมุนจอ = encoder บนมือถือเริ่มใหม่พร้อม SPS/PPS ชุดใหม่ — เริ่ม decoder ใหม่ด้วย
                codec = self._new_decoder()
                config = None
                self.session_changed.emit(header.width, header.height)
                continue
            data = recv_exact(self._sock, header.size)
            if header.config:
                config = data
                continue
            if config is not None:
                data, config = config + data, None
            packet = av.Packet(data)
            packet.pts = header.pts
            for frame in codec.decode(packet):
                self._publish(frame)

    def _publish(self, frame: "av.VideoFrame") -> None:
        now = time.monotonic()
        self._fps_count += 1
        if now - self._fps_since >= 1.0:
            self.fps = self._fps_count / (now - self._fps_since)
            self._fps_count, self._fps_since = 0, now

        tw, th = self._target
        if tw <= 1 or th <= 1:
            tw, th = frame.width, frame.height
        image = frame_to_qimage(frame, tw, th)
        with self._lock:
            self._last_frame = frame
            self._latest = image
            notify = not self._pending
            self._pending = True
        if notify:
            self.frame_ready.emit()


class ControlChannel(QObject):
    """ส่งข้อความควบคุม (thread-safe) + อ่านข้อความจากมือถือ (clipboard) ใน thread แยก."""

    clipboard_received = Signal(str)
    failed = Signal(str)

    def __init__(self, sock: socket.socket, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._sock = sock
        self._lock = threading.Lock()
        self._dead = False
        self._closing = False
        self._reader = threading.Thread(target=self._read_loop, name="scrcpy-control", daemon=True)

    def start(self) -> None:
        self._reader.start()

    def stop(self) -> None:
        self._closing = True

    def send(self, message: bytes) -> bool:
        if self._dead:
            return False
        try:
            with self._lock:
                self._sock.sendall(message)
            return True
        except OSError as e:
            self._dead = True
            if not self._closing:
                self.failed.emit(f"ส่งคำสั่งไปมือถือไม่สำเร็จ: {e}")
            return False

    def _read_loop(self) -> None:
        try:
            while True:
                msg = protocol.read_device_message(lambda n: recv_exact(self._sock, n))
                if isinstance(msg, protocol.ClipboardMessage):
                    self.clipboard_received.emit(msg.text)
        except (ConnectionError, OSError, ValueError):
            pass  # ปิด session / หลุด — VideoReceiver เป็นคนแจ้งผู้ใช้
