"""เปิด/ปิด scrcpy-server บนมือถือ แล้วคืน socket วิดีโอ + socket ควบคุมที่พร้อมใช้.

ลำดับเดียวกับ scrcpy ตัวจริงโหมด --force-adb-forward (doc/develop.md หัวข้อ Connection):
  push jar -> adb forward tcp:<port> localabstract:scrcpy_<scid> -> สั่ง app_process รัน server
  -> ต่อ socket แรก (วิดีโอ) วนจนได้ dummy byte -> ต่อ socket ที่สอง (ควบคุม)
  -> อ่านชื่อเครื่อง 64 byte + codec id 4 byte จาก socket วิดีโอ

ใช้ forward แทน reverse เพราะ adb reverse บางเครื่องใช้ไม่ได้ผ่าน adb แบบเครือข่าย ส่วน forward ใช้ได้ทุก
transport (USB, Wi-Fi, Tailscale) — ข้อเสียคือต้องวน retry เพราะ adb รับ connection ทันทีแม้ server
บนมือถือยังไม่ได้ listen (จึงมี dummy byte ไว้ยืนยันว่าต่อถึงตัวจริงแล้ว)
"""
from __future__ import annotations

import collections
import hashlib
import os
import random
import shlex
import socket
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

import protocol
from adb import Adb, AdbError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_FILE = os.path.join(BASE_DIR, "bin", f"scrcpy-server-v{protocol.SCRCPY_VERSION}")


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamOptions:
    max_size: int = 1024  # ด้านยาวสุดของวิดีโอ (px) — 0 = เท่าจอจริง
    bit_rate: int = 3_000_000
    max_fps: int = 30
    stay_awake: bool = True  # ไม่ให้จอดับระหว่างควบคุม (มีผลเฉพาะตอนมือถือเสียบชาร์จ ตามกลไกของ Android)

    def server_args(self, scid: int) -> List[str]:
        args = [
            f"scid={scid:08x}",
            "log_level=info",
            "tunnel_forward=true",
            "audio=false",
            "control=true",
            "video_codec=h264",
            f"max_size={self.max_size}",
            f"video_bit_rate={self.bit_rate}",
            f"stay_awake={'true' if self.stay_awake else 'false'}",
            "clipboard_autosync=true",
            "power_on=true",
        ]
        if self.max_fps > 0:
            args.append(f"max_fps={self.max_fps}")
        return args


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_server_file(path: str = SERVER_FILE, log: Callable[[str], None] = lambda _m: None) -> str:
    """ดาวน์โหลด scrcpy-server จาก GitHub release ครั้งแรก แล้วตรวจ SHA256 ทุกครั้ง
    (ไฟล์นี้จะถูกรันด้วยสิทธิ์ shell บนมือถือ — ห้ามใช้ไฟล์ที่ hash ไม่ตรงเด็ดขาด)."""
    if os.path.isfile(path) and _sha256(path) == protocol.SERVER_SHA256:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log(f"กำลังดาวน์โหลด scrcpy-server v{protocol.SCRCPY_VERSION} ...")
    tmp = path + ".download"
    try:
        with urllib.request.urlopen(protocol.SERVER_URL, timeout=60) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
    except OSError as e:
        raise SessionError(f"ดาวน์โหลด scrcpy-server ไม่สำเร็จ: {e}") from e
    digest = _sha256(tmp)
    if digest != protocol.SERVER_SHA256:
        os.remove(tmp)
        raise SessionError(f"scrcpy-server ที่ดาวน์โหลดมา hash ไม่ตรง ({digest}) — ไม่ใช้ไฟล์นี้")
    os.replace(tmp, path)
    return path


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("การเชื่อมต่อกับมือถือถูกปิด")
        buf += chunk
    return bytes(buf)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ScrcpySession:
    """หนึ่ง session = server หนึ่งตัวบนมือถือ + socket สองเส้น. ใช้ครั้งเดียว — ต่อใหม่ให้สร้างใหม่."""

    CONNECT_TIMEOUT_S = 20.0  # ข้ามอินเทอร์เน็ต app_process อาจใช้ 2–5 วินาทีกว่าจะ listen

    def __init__(self, adb: Adb, serial: str, options: StreamOptions) -> None:
        self.adb = adb
        self.serial = serial
        self.options = options
        self.device_name = ""
        self.video_sock: Optional[socket.socket] = None
        self.control_sock: Optional[socket.socket] = None
        self._port: Optional[int] = None
        self._process = None
        self._log: Deque[str] = collections.deque(maxlen=200)
        self._closed = False

    # ---- log ของ server (stdout ของ adb shell) ----
    def _pump_log(self) -> None:
        proc = self._process
        for raw in iter(proc.stdout.readline, b""):
            self._log.append(raw.decode("utf-8", errors="replace").rstrip())

    def server_log(self) -> List[str]:
        return list(self._log)

    def _server_error(self) -> str:
        lines = [ln for ln in self._log if "ERROR" in ln or "Exception" in ln or "rror:" in ln]
        return "\n".join(lines[-6:]) or "\n".join(list(self._log)[-6:])

    # ---- เริ่ม ----
    def start(self, log: Callable[[str], None] = lambda _m: None) -> "ScrcpySession":
        try:
            self._start(log)
        except BaseException:
            self.close()
            raise
        return self

    def _start(self, log: Callable[[str], None]) -> None:
        local = ensure_server_file(log=log)
        log("ส่ง scrcpy-server ขึ้นมือถือ ...")
        try:
            self.adb.push(self.serial, local, protocol.DEVICE_SERVER_PATH)
        except AdbError as e:
            raise SessionError(f"ส่งไฟล์ขึ้นมือถือไม่สำเร็จ: {e}") from e

        scid = random.randint(0, 0x7FFF_FFFF)
        self._port = _free_port()
        self.adb.forward(self.serial, self._port, f"localabstract:scrcpy_{scid:08x}")

        command = " ".join(
            [f"CLASSPATH={protocol.DEVICE_SERVER_PATH}", "app_process", "/", "com.genymobile.scrcpy.Server",
             protocol.SCRCPY_VERSION] + [shlex.quote(a) for a in self.options.server_args(scid)]
        )
        log("เปิด server บนมือถือ ...")
        self._process = self.adb.popen(["shell", command], serial=self.serial)
        threading.Thread(target=self._pump_log, name="scrcpy-log", daemon=True).start()

        self.video_sock = self._connect_first_socket()
        self.control_sock = socket.create_connection(("127.0.0.1", self._port), timeout=10)
        for s in (self.video_sock, self.control_sock):
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self.video_sock.settimeout(15)
        self.device_name = protocol.parse_device_name(recv_exact(self.video_sock, protocol.DEVICE_NAME_LENGTH))
        codec = int.from_bytes(recv_exact(self.video_sock, 4), "big")
        if codec != protocol.CODEC_H264:
            # 0/1 = server ปิดสตรีมเอง (เช่นจับภาพหน้าจอไม่ได้) — รายละเอียดอยู่ใน log ของ server
            time.sleep(0.3)
            raise SessionError(f"มือถือส่งวิดีโอไม่ได้ (codec {codec:#x})\n{self._server_error()}")
        # จากนี้ไป thread อ่านวิดีโอ/ควบคุมจะ block รอข้อมูลได้ไม่จำกัด (ปิดด้วย close() เท่านั้น)
        self.video_sock.settimeout(None)
        self.control_sock.settimeout(None)
        log(f"เชื่อมต่อแล้ว: {self.device_name}")

    def _connect_first_socket(self) -> socket.socket:
        deadline = time.monotonic() + self.CONNECT_TIMEOUT_S
        while True:
            if self._process.poll() is not None:
                time.sleep(0.2)  # ให้ thread log เก็บบรรทัดสุดท้ายก่อน
                raise SessionError(f"server บนมือถือหยุดทำงาน\n{self._server_error()}")
            sock = None
            try:
                sock = socket.create_connection(("127.0.0.1", self._port), timeout=5)
                sock.settimeout(2)
                if sock.recv(1) == b"\x00":  # dummy byte = ถึงตัว server จริงแล้ว
                    return sock
            except OSError:
                pass
            if sock is not None:
                sock.close()
            if time.monotonic() > deadline:
                raise SessionError(f"รอ server บนมือถือไม่ไหว (เกิน {self.CONNECT_TIMEOUT_S:.0f} วินาที)\n"
                                   f"{self._server_error()}")
            time.sleep(0.1)

    # ---- ปิด ----
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for s in (self.video_sock, self.control_sock):
            if s is None:
                continue
            try:
                s.shutdown(socket.SHUT_RDWR)  # ปลุก thread ที่ block ใน recv() อยู่
            except OSError:
                pass
            s.close()
        # ปิด socket แล้ว server จะจบเอง (และลบ jar ตัวเองทิ้ง) — รอสั้น ๆ ก่อนฆ่า
        if self._process is not None:
            try:
                self._process.wait(timeout=2)
            except Exception:
                self._process.kill()
        if self._port is not None:
            try:
                self.adb.forward_remove(self.serial, self._port)
            except AdbError:
                pass
