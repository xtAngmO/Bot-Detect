"""เทสต์สร้างหน้าต่างหลักแบบ headless (ไม่ต้องมีจอจริง) — ยิง signal handler ตรงๆ เช็คว่าไม่พัง
รัน: QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe tests\\test_app_smoke.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

import config as config_module
import solver as solver_module
from app import MainWindow
from config import MODE_GRID, MODE_OCR

# ห้ามให้เทสต์เขียนทับ config.json ของผู้ใช้จริง — no-op ก่อน MainWindow ใดๆ จะ save()
# (บทเรียนจากโปรเจกต์พี่น้อง bot_detect_word ที่เคยโดนมาโครหายเพราะสคริปต์ทดสอบ)
config_module.Settings.save = lambda self, *a, **k: None
# standby จับจอจริง + ต่อมือถือจริงตอนว่าง — เทสต์ UI ห้ามไปแตะของจริง
solver_module.Solver.start_standby = lambda self: None


def _window() -> MainWindow:
    QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.solver.start = lambda: None  # ไม่รันบอทจริง
    win.settings.grid_box = (100, 100, 500, 500)
    win.settings.next_box = (650, 100, 120, 60)
    win._refresh_frame_labels()
    return win


def test_main_window_constructs_and_signals_fire() -> None:
    win = _window()
    win._on_log("info", "smoke test log line <b>ไม่ใช่ html</b>")
    win._on_target_found((100, 100, 50, 50), 7)
    win._on_progress(6, 7)
    win._on_finished(False)
    assert win.windowTitle().startswith("Number Sequence Bot")
    assert win.log_section.meta.text() == "1 บรรทัด"
    assert "<b>" in win.log_view.toPlainText()  # ข้อความใน log ถูก escape ไม่กลายเป็น html
    assert win.grid_status.text() == "500 × 500 px @ 100,100"
    win.close()


def test_grid_mode_needs_only_the_grid_frame() -> None:
    win = _window()
    started = []
    win.solver.start = lambda: started.append(win.settings.mode)
    win.settings.next_box = None

    win.mode_seg.set_value(MODE_GRID, emit=True)
    assert win.settings.mode == MODE_GRID
    assert not win.next_toggle.isEnabled() and not win.next_overlay.isVisible()
    assert "ไม่ใช้" in win.next_status.text()
    assert win.control_section.meta.text() == "ตารางอย่างเดียว"
    win._on_run_clicked()  # ไม่มีกรอบเลขต่อไปก็เริ่มได้ในโหมดนี้
    assert started == [MODE_GRID]
    assert not win.mode_seg.isEnabled(), "ระหว่างรันห้ามสลับโหมด"
    win._on_finished(True)

    win.mode_seg.set_value(MODE_OCR, emit=True)
    assert win.settings.mode == MODE_OCR and win.next_toggle.isEnabled()
    win.close()


def test_status_shows_running_and_why_it_stopped() -> None:
    win = _window()
    assert win.status.state() == "idle"

    win._on_run_clicked()  # เริ่ม
    assert win.status.state() == "starting"
    assert win.run_btn.property("kind") == "stop" and win.run_btn.text() == "หยุด"
    assert win.windowTitle().startswith("▶")
    win._on_target_found((100, 100, 50, 50), 12)
    assert win.status.state() == "running" and "12" in win.detail_label.text()
    assert win.stat_next.text() == "12"
    win._on_finished(True)
    assert win.status.state() == "done"
    assert win.run_btn.property("kind") == "primary" and win.run_btn.text() == "เริ่มอัตโนมัติ"
    assert not win.windowTitle().startswith("▶")

    stopped = []
    win.solver.stop = lambda: stopped.append(True)
    win._on_run_clicked()  # เริ่ม
    win._on_run_clicked()  # ปุ่มเดียวกัน = หยุด
    assert stopped and win.detail_label.text() == "กำลังหยุด…"
    win._on_finished(False)
    assert win.status.state() == "stopped"

    win._on_run_clicked()
    win._on_log("error", "อ่านตารางไม่ได้ติดกัน 20 ครั้ง หยุดเพื่อความปลอดภัย")
    win._on_finished(False)
    assert win.status.state() == "error" and "20 ครั้ง" in win.detail_label.text()

    win._on_ready("⚡ อ่านตารางไว้แล้ว — กดเริ่มได้ทันที (เลขต่อไป 1)")
    assert "กดเริ่มได้ทันที" in win.ready_label.text()
    win.close()


def test_grid_frame_draws_cell_lines_and_stays_click_through() -> None:
    win = _window()
    ov = win.grid_overlay
    ov.resize(5 * 60 + 12, 5 * 80 + 12)  # ด้านใน 300×400 → ช่องละ 60×80 (ขอบกรอบหนา 6)
    win.rows_spin.setValue(5)
    win.cols_spin.setValue(5)
    ov.set_grid(5, 5)
    mask = ov.mask()
    # เส้นต้องอยู่ใน mask (ไม่งั้นวาดไม่ติด) แต่กลางช่องต้องไม่อยู่ — คลิกทะลุไปโดนเกมข้างล่าง
    assert mask.contains(QPoint(6 + 60, 6 + 30)), "เส้นแนวตั้งระหว่างคอลัมน์ 0|1"
    assert mask.contains(QPoint(6 + 30, 6 + 80)), "เส้นแนวนอนระหว่างแถว 0|1"
    assert not mask.contains(QPoint(6 + 30, 6 + 40)), "กลางช่อง (0,0) ต้องคลิกทะลุ"
    win.cols_spin.setValue(4)  # แก้คอลัมน์ → เส้นย้ายตามทันที (ช่องละ 75)
    assert ov.mask().contains(QPoint(6 + 75, 6 + 30)) and not ov.mask().contains(QPoint(6 + 60, 6 + 30))
    win.close()


def test_log_sits_right_under_control() -> None:
    win = _window()
    col = win.control_section.parentWidget().layout()
    assert col.indexOf(win.log_section) == col.indexOf(win.control_section) + 1
    win.close()


if __name__ == "__main__":
    test_main_window_constructs_and_signals_fire()
    test_grid_mode_needs_only_the_grid_frame()
    test_status_shows_running_and_why_it_stopped()
    test_grid_frame_draws_cell_lines_and_stays_click_through()
    test_log_sits_right_under_control()
    print("test_app_smoke.py OK")
