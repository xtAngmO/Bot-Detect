"""เทสต์ตัวแปลงผลลัพธ์ของ adb/tailscale — parse ล้วน ไม่เรียก subprocess จริง.
รัน:  python tests/test_adb.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adb
from connect_dialog import split_host_port


def test_parse_devices_usb_and_network() -> None:
    output = (
        "List of devices attached\n"
        "R58N12ABCDE            device usb:1-1 product:x model:SM_G991B device:o1s transport_id:1\n"
        "100.64.1.2:5555        device product:y model:Pixel_7 device:panther transport_id:2\n"
        "emulator-5554          offline\n"
        "9A271FFBC1             unauthorized transport_id:3\n"
    )
    devices = adb.parse_devices(output)
    assert len(devices) == 4
    usb, net, offline, unauth = devices
    assert usb.serial == "R58N12ABCDE" and usb.state == "device" and usb.model == "SM_G991B"
    assert usb.is_network is False
    assert net.serial == "100.64.1.2:5555" and net.is_network is True and net.model == "Pixel_7"
    assert offline.state == "offline"
    assert unauth.state == "unauthorized"
    # label ต้องบอกชนิดการต่อและสถานะให้ผู้ใช้อ่านออก
    assert "USB" in usb.label
    assert "เน็ต" in net.label
    assert "unauthorized" in unauth.label


def test_parse_devices_ignores_daemon_noise() -> None:
    output = ("* daemon not running; starting now at tcp:5037\n"
              "* daemon started successfully\n"
              "List of devices attached\n")
    assert adb.parse_devices(output) == []


def test_parse_tailscale_status_sorts_android_online_first() -> None:
    data = {
        "Peer": {
            "a": {"HostName": "windows-pc", "TailscaleIPs": ["100.1.1.1"], "OS": "windows", "Online": True},
            "b": {"HostName": "my-pixel", "TailscaleIPs": ["100.2.2.2", "fd7a::1"], "OS": "android", "Online": True},
            "c": {"HostName": "old-phone", "TailscaleIPs": ["100.3.3.3"], "OS": "android", "Online": False},
        }
    }
    peers = adb.parse_tailscale_status(data)
    assert [p.name for p in peers] == ["my-pixel", "old-phone", "windows-pc"]
    assert peers[0].ip == "100.2.2.2"  # เลือก IPv4 ไม่ใช่ IPv6
    assert "ออฟไลน์" in peers[1].label


def test_parse_tailscale_status_empty() -> None:
    assert adb.parse_tailscale_status({}) == []
    assert adb.parse_tailscale_status({"Peer": {}}) == []


def test_split_host_port() -> None:
    assert split_host_port("100.64.1.2:41235") == ("100.64.1.2", "41235")
    assert split_host_port("my-pixel (100.64.1.2)") == ("100.64.1.2", "")
    assert split_host_port("  100.64.1.2  ") == ("100.64.1.2", "")


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("test_adb.py OK")


if __name__ == "__main__":
    _run_all()
