"""Entry point — Number Sequence Bot."""
from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()

    # Ctrl+C ในเทอร์มินัล: ถ้าไม่ดักเอง Python จะ raise KeyboardInterrupt กลาง callback ของ Qt ตัวไหน
    # ก็ได้ (เช่น _tick_elapsed) แล้วแอปตายพร้อม traceback โดยไม่ได้ save config — ดักแล้วปิดหน้าต่าง
    # ตามปกติแทน (closeEvent หยุด solver + save ให้). timer เปล่าๆ มีไว้ให้ Python ได้จังหวะเช็ค signal
    # เป็นระยะ เพราะระหว่างรอ event ใน C++ ของ Qt ตัว handler จะไม่ถูกเรียกเลย
    signal.signal(signal.SIGINT, lambda *_: (win.close(), app.quit()))
    sigint_pump = QTimer()
    sigint_pump.timeout.connect(lambda: None)
    sigint_pump.start(200)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
