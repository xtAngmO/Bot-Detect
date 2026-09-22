"""ตัวห่อคำสั่ง adb และ tailscale — เรียกผ่าน subprocess ทั้งหมด ไม่มีสถานะค้างใน process เรา.

ทุกฟังก์ชันที่นี่ block (adb connect ข้ามอินเทอร์เน็ตอาจนานหลายวินาที) ห้ามเรียกจาก GUI thread ตรง ๆ
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence

# Windows: ไม่ให้ adb.exe/tailscale.exe เด้งหน้าต่าง console ดำขึ้นมาทุกครั้งที่เรียก
# (บน macOS/Linux ค่านี้เป็น 0 = creationflags ปกติ — getattr กันไม่ให้ AttributeError)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_IS_WINDOWS = sys.platform == "win32"
_EXE = ".exe" if _IS_WINDOWS else ""


class AdbError(RuntimeError):
    pass


def find_adb(explicit: str = "") -> str:
    """หา adb: ค่าที่ตั้งเอง -> PATH -> Android SDK (Android Studio) -> ANDROID_HOME/ANDROID_SDK_ROOT.
    รองรับทั้ง Windows (adb.exe) และ macOS/Linux (adb ที่ ~/Library/Android/sdk หรือ ~/Android/Sdk)."""
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        raise AdbError(f"ไม่พบ adb ที่ตั้งไว้: {explicit}")
    found = shutil.which("adb")
    if found:
        return found
    candidates = []
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(env):
            candidates.append(os.path.join(os.environ[env], "platform-tools", "adb" + _EXE))
    home = os.path.expanduser("~")
    if _IS_WINDOWS and os.environ.get("LOCALAPPDATA"):
        candidates.append(os.path.join(os.environ["LOCALAPPDATA"], "Android", "Sdk", "platform-tools", "adb.exe"))
    else:
        # ตำแหน่งเริ่มต้นของ Android SDK บน macOS และ Linux
        candidates.append(os.path.join(home, "Library", "Android", "sdk", "platform-tools", "adb"))
        candidates.append(os.path.join(home, "Android", "Sdk", "platform-tools", "adb"))
        candidates.append("/opt/homebrew/bin/adb")  # brew บน Apple Silicon
        candidates.append("/usr/local/bin/adb")     # brew บน Intel Mac
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise AdbError(
        "ไม่พบ adb — ติดตั้ง Android SDK Platform-Tools "
        "(https://developer.android.com/tools/releases/platform-tools) แล้วเพิ่มเข้า PATH "
        "(macOS: brew install android-platform-tools)"
    )


@dataclass(frozen=True)
class Device:
    serial: str  # เช่น "R58N12ABCDE" (USB), "100.64.1.2:5555" (เครือข่าย), "adb-XXXX._adb-tls-connect._tcp" (mDNS)
    state: str  # device / unauthorized / offline
    model: str = ""

    @property
    def is_network(self) -> bool:
        return ":" in self.serial or "._adb-tls-connect." in self.serial

    @property
    def label(self) -> str:
        name = self.model.replace("_", " ") if self.model else self.serial
        kind = "เน็ต" if self.is_network else "USB"
        extra = "" if self.state == "device" else f" — {self.state}"
        return f"{name}  [{kind}: {self.serial}]{extra}"


def parse_devices(output: str) -> List[Device]:
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        model = ""
        for token in parts[2:]:
            if token.startswith("model:"):
                model = token[len("model:"):]
        devices.append(Device(serial=parts[0], state=parts[1], model=model))
    return devices


class Adb:
    def __init__(self, path: str = "") -> None:
        self.path = find_adb(path)

    def run(self, args: Sequence[str], serial: Optional[str] = None, timeout: float = 30.0,
            check: bool = True) -> str:
        cmd = [self.path] + (["-s", serial] if serial else []) + list(args)
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb {' '.join(args)}: หมดเวลา {timeout:.0f} วินาที") from e
        out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace").strip()
        if check and proc.returncode != 0:
            raise AdbError(out or f"adb {' '.join(args)} exited {proc.returncode}")
        return out

    def popen(self, args: Sequence[str], serial: Optional[str] = None) -> subprocess.Popen:
        cmd = [self.path] + (["-s", serial] if serial else []) + list(args)
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)

    def devices(self) -> List[Device]:
        return parse_devices(self.run(["devices", "-l"], timeout=15))

    def connect(self, address: str) -> str:
        """adb connect ตอบ exit 0 แม้ต่อไม่ติด ("failed to connect ...") ต้องอ่านข้อความเอง."""
        out = self.run(["connect", address], timeout=25, check=False)
        if "connected to" not in out:  # "connected to X" และ "already connected to X"
            raise AdbError(out or f"เชื่อมต่อ {address} ไม่สำเร็จ")
        return out

    def disconnect(self, address: str) -> str:
        return self.run(["disconnect", address], timeout=10, check=False)

    def pair(self, address: str, code: str) -> str:
        out = self.run(["pair", address, code], timeout=30, check=False)
        if "Successfully paired" not in out:
            raise AdbError(out or f"จับคู่ {address} ไม่สำเร็จ")
        return out

    def push(self, serial: str, local: str, remote: str) -> None:
        self.run(["push", local, remote], serial=serial, timeout=120)

    def forward(self, serial: str, local_port: int, remote: str) -> None:
        self.run(["forward", f"tcp:{local_port}", remote], serial=serial, timeout=15)

    def forward_remove(self, serial: str, local_port: int) -> None:
        self.run(["forward", "--remove", f"tcp:{local_port}"], serial=serial, timeout=10, check=False)

    def shell(self, serial: str, command: str, timeout: float = 20.0) -> str:
        return self.run(["shell", command], serial=serial, timeout=timeout)


# ---------------------------------------------------------------- Tailscale

@dataclass(frozen=True)
class TailscalePeer:
    name: str
    ip: str
    os: str
    online: bool

    @property
    def label(self) -> str:
        return f"{self.name} ({self.ip}){'' if self.online else ' — ออฟไลน์'}"


def find_tailscale() -> Optional[str]:
    found = shutil.which("tailscale")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Tailscale\tailscale.exe",
        # macOS: ทั้งแบบติดตั้งจาก App Store และจาก tailscale.com
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
        "/opt/homebrew/bin/tailscale",
        "/usr/local/bin/tailscale",
    ]
    return next((p for p in candidates if os.path.isfile(p)), None)


_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def parse_tailscale_status(data: dict) -> List[TailscalePeer]:
    peers = []
    for peer in (data.get("Peer") or {}).values():
        ips = [ip for ip in peer.get("TailscaleIPs") or [] if _IPV4.match(ip)]
        if not ips:
            continue
        name = peer.get("HostName") or (peer.get("DNSName") or "").split(".")[0] or ips[0]
        peers.append(TailscalePeer(name=name, ip=ips[0], os=(peer.get("OS") or "").lower(),
                                   online=bool(peer.get("Online"))))
    # มือถือ Android ที่ออนไลน์ขึ้นก่อน — ส่วนใหญ่ผู้ใช้จะเลือกตัวนั้น
    peers.sort(key=lambda p: (p.os != "android", not p.online, p.name.lower()))
    return peers


def tailscale_peers() -> List[TailscalePeer]:
    """รายชื่อเครื่องใน tailnet เดียวกัน — คืน [] ถ้าไม่ได้ลง/ไม่ได้ล็อกอิน Tailscale."""
    exe = find_tailscale()
    if not exe:
        return []
    try:
        proc = subprocess.run([exe, "status", "--json"], capture_output=True, timeout=10,
                              creationflags=_NO_WINDOW)
        return parse_tailscale_status(json.loads(proc.stdout.decode("utf-8", errors="replace")))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
