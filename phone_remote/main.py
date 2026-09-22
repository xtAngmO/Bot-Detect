"""Phone Remote — ดูจอมือถือ Android บนคอม/แมค แล้วสั่งงานด้วยเมาส์+คีย์บอร์ด.

รัน:  python main.py       (ต้องมี PySide6, av; และมี adb ในเครื่อง)
เชื่อมต่อ: USB, Wi‑Fi วงเดียวกัน หรือข้ามเน็ตผ่าน Tailscale
"""
from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from connect_dialog import ConnectDialog
from settings import Settings


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Phone Remote")
    settings = Settings.load()
    dialog = ConnectDialog(settings)
    dialog.show()

    # Ctrl+C ในเทอร์มินัล: ดักเองแล้วปิดแอปตามปกติ (timer เปล่า ๆ ให้ Python ได้จังหวะเช็ค signal
    # ระหว่างที่ event loop ของ Qt กำลัง block อยู่ใน C++) — แนวเดียวกับ main.py ของบอทเรียงเลข
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    pump = QTimer()
    pump.timeout.connect(lambda: None)
    pump.start(200)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
