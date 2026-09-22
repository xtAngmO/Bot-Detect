"""แตะมือถือตรงผ่าน scrcpy-server ตัวที่สอง (control อย่างเดียว) — แทนการคลิกลงหน้าต่าง scrcpy

ทำไม: คลิกลงหน้าต่าง scrcpy ด้วย SendInput ไม่ถึงเลยบนเครื่องผู้ใช้ และ PostMessage พลาดเป็นช่วงๆ (SDL
ประมวล WM_MOUSELEAVE แทรกระหว่าง move กับ down แล้วย้ายตำแหน่งไปที่เมาส์จริง — log จริง: เกมไม่รับแตะช่อง
เดิมซ้ำ 2 รอบติด แม้เป็นแตะแรกหลังหยุดรอ 1.5s). เปิด server ของ scrcpy อีกตัวบนมือถือ (scid ของตัวเอง,
video=false) แล้วส่ง INJECT_TOUCH_EVENT ด้วยพิกัดมือถือตรงๆ ไม่ผ่าน Windows/เมาส์เลย — วัดด้วย Pointer
location แล้วแตะตรงจุด ต่อเสร็จ ~0.5s. scrcpy ตัวจริงของผู้ใช้ทำงานต่อได้ตามปกติ (server คนละตัว)

**ใช้ adb.exe + scrcpy-server จากโฟลเดอร์เดียวกับ scrcpy.exe ที่เปิดหน้าต่างอยู่เสมอ** — adb คนละเวอร์ชันจะ
kill adb server ของ scrcpy ตัวจริงทิ้ง ("adb server version (40) doesn't match this client (41); killing...")
และ scrcpy-server ต้องเวอร์ชันเดียวกับที่บอกตอนเปิด (อ่านจาก `scrcpy.exe --version`)
"""
from __future__ import annotations

import ctypes
import os
import random
import re
import socket
import struct
import subprocess
import threading
import time
from ctypes import wintypes
from typing import List, Optional, Tuple

DEVICE_JAR = "/data/local/tmp/hiu-bot-scrcpy-server.jar"  # คนละ path กับของ scrcpy ตัวจริง
# INJECT_TOUCH_EVENT ของ scrcpy 4.x (byte อ้างอิงอยู่ใน tests/test_phonetap.py — เทียบกับซอร์ส v4.1 แล้ว):
# type, action, pointer_id, x, y, screen_w, screen_h, pressure (u16 fixed), action_button, buttons
_TOUCH = struct.Struct(">BBQiiHHHii")
_TYPE_INJECT_TOUCH_EVENT = 2
ACTION_DOWN = 0
ACTION_UP = 1
_POINTER_ID_GENERIC_FINGER = -2  # server ฉีดเป็นนิ้วแตะจอ (SOURCE_TOUCHSCREEN)
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW — ไม่ให้ adb เด้งหน้าต่าง console


class PhoneTapError(RuntimeError):
    pass


def touch_message(action: int, x: int, y: int, width: int, height: int) -> bytes:
    """(width, height) ต้องเท่ากับขนาดจอมือถือในทิศปัจจุบันเป๊ะ ไม่งั้น server ทิ้ง event เงียบๆ."""
    pressure = 0xFFFF if action == ACTION_DOWN else 0
    return _TOUCH.pack(_TYPE_INJECT_TOUCH_EVENT, action, _POINTER_ID_GENERIC_FINGER & 0xFFFF_FFFF_FFFF_FFFF,
                       x, y, width, height, pressure, 0, 0)


def parse_devices(text: str) -> List[Tuple[str, str]]:
    """ผลของ `adb devices -l` → [(serial, model)] เฉพาะเครื่องที่สถานะ device."""
    found = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
            found.append((parts[0], model))
    return found


def pick_serial(devices: List[Tuple[str, str]], window_title: str) -> str:
    """เครื่องเดียวใช้เลย; หลายเครื่องเลือกตัวที่ model ตรงกับชื่อหน้าต่าง scrcpy (ค่าเริ่มต้นคือชื่อรุ่น)."""
    if len(devices) == 1:
        return devices[0][0]
    matches = [s for s, model in devices if model and model == window_title.strip()]
    if len(matches) == 1:
        return matches[0]
    raise PhoneTapError(f"เลือกมือถือไม่ได้ (เจอ {len(devices)} เครื่อง, หน้าต่างชื่อ {window_title!r})")


def parse_wm_size(text: str) -> Tuple[int, int]:
    """ผลของ `wm size` → (w, h) แนวตั้ง — ใช้ Override size ก่อนถ้ามีการตั้งไว้."""
    sizes = dict(re.findall(r"(Physical|Override) size: (\d+x\d+)", text))
    raw = sizes.get("Override") or sizes.get("Physical")
    if not raw:
        raise PhoneTapError(f"อ่านขนาดจอมือถือไม่ได้: {text.strip()!r}")
    w, h = (int(v) for v in raw.split("x"))
    return w, h


def exe_dir_of_pid(pid: int) -> str:
    k = ctypes.WinDLL("kernel32")
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise PhoneTapError(f"เปิด process {pid} ไม่ได้")
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            raise PhoneTapError(f"อ่าน path ของ process {pid} ไม่ได้")
        return os.path.dirname(buf.value)
    finally:
        k.CloseHandle(handle)


class PhoneTapper:
    """หนึ่งตัวต่อ scrcpy หนึ่งหน้าต่าง: server ตัวที่สองบนมือถือ + socket control หนึ่งเส้น."""

    CONNECT_TIMEOUT_S = 10.0

    def __init__(self, scrcpy_dir: str, window_title: str = "") -> None:
        self.adb = os.path.join(scrcpy_dir, "adb.exe")
        self.server = os.path.join(scrcpy_dir, "scrcpy-server")
        self.scrcpy = os.path.join(scrcpy_dir, "scrcpy.exe")
        self.window_title = window_title
        self.serial = ""
        self.size: Tuple[int, int] = (0, 0)  # แนวตั้ง
        self._sock: Optional[socket.socket] = None
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._lock = threading.Lock()
        self.alive = False

    # ---- เชื่อมต่อ ------------------------------------------------------------
    def _run(self, *args: str, serial: bool = True, timeout: float = 15.0) -> str:
        cmd = [self.adb] + (["-s", self.serial] if serial and self.serial else []) + list(args)
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
        if done.returncode != 0:
            raise PhoneTapError(f"adb {' '.join(args)} ล้มเหลว: {(done.stderr or done.stdout).strip()}")
        return done.stdout

    def _version(self) -> str:
        out = subprocess.run([self.scrcpy, "--version"], capture_output=True, text=True, timeout=10,
                             creationflags=_NO_WINDOW).stdout
        m = re.search(r"scrcpy (\d+(?:\.\d+)+)", out)
        if not m:
            raise PhoneTapError(f"อ่านเวอร์ชัน scrcpy ไม่ได้: {out.strip()[:80]!r}")
        return m.group(1)

    def connect(self) -> "PhoneTapper":
        for path in (self.adb, self.server, self.scrcpy):
            if not os.path.isfile(path):
                raise PhoneTapError(f"ไม่พบ {os.path.basename(path)} ข้าง scrcpy.exe ({os.path.dirname(path)})")
        version = self._version()
        self.serial = pick_serial(parse_devices(self._run("devices", "-l", serial=False)), self.window_title)
        self.size = parse_wm_size(self._run("shell", "wm", "size"))
        self._run("push", self.server, DEVICE_JAR, timeout=30)
        scid = random.randint(0, 0x7FFF_FFFF)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self._port = probe.getsockname()[1]
        self._run("forward", f"tcp:{self._port}", f"localabstract:scrcpy_{scid:08x}")
        args = [f"scid={scid:08x}", "log_level=warn", "tunnel_forward=true", "video=false", "audio=false",
                "control=true", "cleanup=true", "power_on=false", "clipboard_autosync=false"]
        command = f"CLASSPATH={DEVICE_JAR} app_process / com.genymobile.scrcpy.Server {version} " + " ".join(args)
        self._proc = subprocess.Popen([self.adb, "-s", self.serial, "shell", command], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        try:
            self._sock = self._handshake(self._port)
        except BaseException:
            self.close()
            raise
        return self

    def _handshake(self, port: int) -> socket.socket:
        """socket แรกได้ dummy byte (= ถึงตัว server จริง) ตามด้วยชื่อเครื่อง 64 byte แล้วเป็น control ล้วน."""
        deadline = time.monotonic() + self.CONNECT_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise PhoneTapError("server บนมือถือหยุดทำงานก่อนต่อได้")
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=2)
            except OSError:
                time.sleep(0.1)
                continue
            try:
                sock.settimeout(2)
                if sock.recv(1) == b"\x00":
                    meta = b""
                    while len(meta) < 64:
                        chunk = sock.recv(64 - len(meta))
                        if not chunk:
                            raise OSError("ปิดระหว่างส่งชื่อเครื่อง")
                        meta += chunk
                    sock.settimeout(None)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.alive = True
                    threading.Thread(target=self._drain, args=(sock,), daemon=True).start()
                    return sock
            except OSError:
                pass
            sock.close()
            time.sleep(0.1)
        raise PhoneTapError(f"รอ server บนมือถือเกิน {self.CONNECT_TIMEOUT_S:.0f} วินาที")

    def _drain(self, sock: socket.socket) -> None:
        """อ่านทิ้ง (server แทบไม่ส่งอะไรมาเพราะปิด clipboard sync) แค่ไว้รู้ตอนการเชื่อมต่อหลุด."""
        try:
            while sock.recv(4096):
                pass
        except OSError:
            pass
        self.alive = False

    # ---- แตะ -------------------------------------------------------------------
    def tap(self, fx: float, fy: float, hold_s: float = 0.03, landscape: bool = False) -> None:
        """แตะที่ตำแหน่งสัดส่วน (fx, fy) ∈ [0, 1] ของจอมือถือ."""
        w, h = self.size
        if landscape and w < h:
            w, h = h, w
        x = min(w - 1, max(0, int(fx * w)))
        y = min(h - 1, max(0, int(fy * h)))
        with self._lock:
            if not self.alive or self._sock is None:
                raise PhoneTapError("การเชื่อมต่อกับมือถือหลุด")
            try:
                self._sock.sendall(touch_message(ACTION_DOWN, x, y, w, h))
                time.sleep(hold_s)
                self._sock.sendall(touch_message(ACTION_UP, x, y, w, h))
            except OSError as exc:
                self.alive = False
                raise PhoneTapError(f"ส่งแตะไม่สำเร็จ: {exc}") from exc

    def describe(self) -> str:
        return f"แตะตรงเข้ามือถือ {self.window_title or self.serial} ({self.size[0]}×{self.size[1]})"

    def close(self) -> None:
        self.alive = False
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None
        # ปิด socket แล้ว server จบเองและลบ jar ตัวเองทิ้ง (cleanup=true) — รอสั้นๆ ก่อนฆ่า
        if self._proc is not None:
            try:
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
            self._proc = None
        if self._port is not None:
            try:
                self._run("forward", "--remove", f"tcp:{self._port}", timeout=5)
            except Exception:
                pass
            self._port = None
