"""เทสต์สร้างหน้าต่างหลักแบบ headless (ไม่ต้องมีจอจริง) — ยิง signal handler ตรงๆ เช็คว่าไม่พัง
รัน: QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe tests\\test_app_smoke.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import config as config_module
from app import MainWindow

# ห้ามให้เทสต์เขียนทับ config.json ของผู้ใช้จริง — no-op ก่อน MainWindow ใดๆ จะ save()
# (บทเรียนจากโปรเจกต์พี่น้อง bot_detect_word ที่เคยโดนมาโครหายเพราะสคริปต์ทดสอบ)
config_module.Settings.save = lambda self, *a, **k: None


def test_main_window_constructs_and_signals_fire() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()

    win.settings.grid_box = (100, 100, 500, 500)
    win.settings.next_box = (650, 100, 120, 60)
    win.solver.settings = win.settings
    win._refresh_frame_labels()

    win._on_log("info", "smoke test log line")
    win._on_target_found((100, 100, 50, 50), 7)
    win._on_progress(6, 7)
    win._on_finished(False)

    assert win.windowTitle().startswith("Number Sequence Bot")
    win.close()


if __name__ == "__main__":
    test_main_window_constructs_and_signals_fire()
    print("test_app_smoke.py OK")
