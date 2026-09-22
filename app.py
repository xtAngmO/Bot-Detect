"""หน้าต่างควบคุมหลักของ Number Sequence Bot (PySide6)."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import capture
from config import Settings
from overlay import FrameOverlay, HighlightRing
from solver import Solver

try:
    import keyboard  # global hotkey (panic key) — ต้องรันแบบ Administrator บางเครื่อง
except Exception:  # pragma: no cover — เครื่องที่ยังไม่ได้ pip install
    keyboard = None

_QSS = """
QWidget { background: #0a0a0a; color: #ededed; font-family: 'Segoe UI'; font-size: 13px; }
QPushButton {
  background: #161618; border: 1px solid #262628; border-radius: 8px;
  padding: 8px 14px; color: #ededed;
}
QPushButton:hover { background: #1f1f22; border-color: #3a3a3d; }
QPushButton:pressed { background: #0e0e10; }
QPushButton#start { background: #22c55e; color: #0a0a0a; font-weight: 600; border: none; }
QPushButton#start:hover { background: #16a34a; }
QPushButton#stop { background: #ef4444; color: #fafafa; font-weight: 600; border: none; }
QPushButton#stop:hover { background: #dc2626; }
QLabel#lead { font-family: 'JetBrains Mono','Consolas',monospace; font-size: 22px; font-weight: 600; }
QLabel#dim { color: #808080; font-size: 11px; }
QPlainTextEdit {
  background: #070708; border: 1px solid #262628; border-radius: 8px;
  font-family: 'JetBrains Mono','Consolas',monospace; font-size: 12px; color: #a0a0a0;
}
QSpinBox { background: #161618; border: 1px solid #262628; border-radius: 6px; padding: 4px; }
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Number Sequence Bot — บอทเรียงเลข")
        self.resize(420, 640)
        self.setStyleSheet(_QSS)

        self.settings = Settings.load()
        capture.configure_tesseract(self.settings.tesseract_cmd)

        self.grid_overlay = FrameOverlay("กรอบตาราง 5×5", "#22c55e", on_change=self._on_grid_change)
        self.next_overlay = FrameOverlay("กรอบเลขต่อไป", "#3b82f6", on_change=self._on_next_change)
        self._restore_overlay_geometry()

        self.highlight = HighlightRing()

        self.solver = Solver(self.settings)
        self.solver.log.connect(self._on_log)
        self.solver.target_found.connect(self._on_target_found)
        self.solver.progress.connect(self._on_progress)
        self.solver.finished.connect(self._on_finished)

        self._run_start_ts: float | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._build_ui()
        self._register_panic_key()

    # ---- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("🎯 Number Sequence Bot")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        layout.addWidget(title)

        # --- frame controls ---
        self.grid_toggle = QPushButton()
        self.grid_toggle.clicked.connect(self._toggle_grid_overlay)
        self.grid_status = QLabel()
        self.grid_status.setObjectName("dim")
        layout.addWidget(self.grid_toggle)
        layout.addWidget(self.grid_status)

        self.next_toggle = QPushButton()
        self.next_toggle.clicked.connect(self._toggle_next_overlay)
        self.next_status = QLabel()
        self.next_status.setObjectName("dim")
        layout.addWidget(self.next_toggle)
        layout.addWidget(self.next_status)
        self._refresh_frame_labels()

        # --- settings ---
        form = QFormLayout()
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 20)
        self.rows_spin.setValue(self.settings.rows)
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 20)
        self.cols_spin.setValue(self.settings.cols)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 400)
        self.max_spin.setValue(self.settings.max_number)
        # เวลาจากคลิกแรกถึงคลิกสุดท้าย — บอทเว้นจังหวะคลิกให้เท่ากันเอง (0 = เร็วสุดเท่าที่ทำได้)
        self.target_time_spin = QSpinBox()
        self.target_time_spin.setRange(0, 600)
        self.target_time_spin.setSpecialValueText("เร็วสุด")
        self.target_time_spin.setValue(self.settings.target_total_s)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 5000)
        self.delay_spin.setSingleStep(50)
        self.delay_spin.setValue(self.settings.click_delay_ms)
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(50, 5000)
        self.poll_spin.setSingleStep(50)
        self.poll_spin.setValue(self.settings.poll_interval_ms)
        form.addRow("แถว × คอลัมน์", self._hbox(self.rows_spin, self.cols_spin))
        form.addRow("เลขสูงสุด", self.max_spin)
        form.addRow("เวลาเป้าหมาย (วินาที)", self.target_time_spin)
        form.addRow("หน่วงหลังคลิก (ms)", self.delay_spin)
        form.addRow("รอบตรวจซ้ำ (ms)", self.poll_spin)
        layout.addLayout(form)

        panic_label = QLabel(f"⛔ Panic key: {self.settings.panic_key.upper()} (หยุดฉุกเฉินได้ทุกเมื่อ)")
        panic_label.setObjectName("dim")
        layout.addWidget(panic_label)

        # --- start/stop ---
        self.start_btn = QPushButton("▶ เริ่มอัตโนมัติ")
        self.start_btn.setObjectName("start")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("■ หยุด")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)

        # --- live status ---
        status_row = QHBoxLayout()
        self.target_label = QLabel("—")
        self.target_label.setObjectName("lead")
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("lead")
        self.elapsed_label = QLabel("0.00s")
        self.elapsed_label.setObjectName("lead")
        status_row.addWidget(self._stat_block("เป้าหมาย", self.target_label))
        status_row.addWidget(self._stat_block("กดแล้ว", self.progress_label))
        status_row.addWidget(self._stat_block("เวลา", self.elapsed_label))
        layout.addLayout(status_row)

        # --- log ---
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, stretch=1)

        self.setCentralWidget(root)

    @staticmethod
    def _hbox(*widgets: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            h.addWidget(widget)
        return w

    @staticmethod
    def _stat_block(caption: str, value_label: QLabel) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        cap = QLabel(caption)
        cap.setObjectName("dim")
        v.addWidget(cap)
        v.addWidget(value_label)
        return w

    # ---- overlay wiring ------------------------------------------------------
    def _restore_overlay_geometry(self) -> None:
        if self.settings.grid_box:
            x, y, w, h = self.settings.grid_box
            self.grid_overlay.move(x - 6, y - 6)
            self.grid_overlay.resize(w + 12, h + 12)
        if self.settings.next_box:
            x, y, w, h = self.settings.next_box
            self.next_overlay.move(x - 6, y - 6)
            self.next_overlay.resize(w + 12, h + 12)

    def _on_grid_change(self, rect) -> None:
        self.settings.grid_box = rect
        self._refresh_frame_labels()

    def _on_next_change(self, rect) -> None:
        self.settings.next_box = rect
        self._refresh_frame_labels()

    def _refresh_frame_labels(self) -> None:
        self.grid_toggle.setText(
            "🙈 ซ่อนกรอบตาราง" if self.grid_overlay.isVisible() else "👁 แสดงกรอบตาราง"
        )
        self.next_toggle.setText(
            "🙈 ซ่อนกรอบเลขต่อไป" if self.next_overlay.isVisible() else "👁 แสดงกรอบเลขต่อไป"
        )
        self.grid_status.setText(
            f"ตั้งกรอบแล้ว {self.settings.grid_box}" if self.settings.grid_box else "ยังไม่ตั้งกรอบ"
        )
        self.next_status.setText(
            f"ตั้งกรอบแล้ว {self.settings.next_box}" if self.settings.next_box else "ยังไม่ตั้งกรอบ"
        )

    def _toggle_grid_overlay(self) -> None:
        self.grid_overlay.setVisible(not self.grid_overlay.isVisible())
        self._refresh_frame_labels()

    def _toggle_next_overlay(self) -> None:
        self.next_overlay.setVisible(not self.next_overlay.isVisible())
        self._refresh_frame_labels()

    # ---- start/stop ------------------------------------------------------------
    def _pull_settings_from_ui(self) -> None:
        self.settings.rows = self.rows_spin.value()
        self.settings.cols = self.cols_spin.value()
        self.settings.max_number = self.max_spin.value()
        self.settings.target_total_s = self.target_time_spin.value()
        self.settings.click_delay_ms = self.delay_spin.value()
        self.settings.poll_interval_ms = self.poll_spin.value()

    def _start(self) -> None:
        self._pull_settings_from_ui()
        if not self.settings.grid_box or not self.settings.next_box:
            QMessageBox.warning(self, "ยังไม่พร้อม", "ตั้งกรอบตารางและกรอบเลขต่อไปก่อนเริ่มอัตโนมัติ")
            return
        self.settings.save()
        self._run_start_ts = time.monotonic()
        self._elapsed_timer.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_label.setText(f"0 / {self.settings.max_number}")
        self.solver.start()

    def _stop(self) -> None:
        self.solver.stop()

    def _panic(self) -> None:
        self.solver.stop()

    def _register_panic_key(self) -> None:
        if keyboard is None:
            self._on_log("warn", "ไลบรารี keyboard ใช้ไม่ได้ — panic key จะไม่ทำงาน (pip install keyboard)")
            return
        try:
            keyboard.add_hotkey(self.settings.panic_key, self._panic)
        except Exception as exc:  # pragma: no cover
            self._on_log("warn", f"ตั้ง panic key ไม่สำเร็จ: {exc}")

    # ---- solver signal handlers ------------------------------------------------
    def _on_log(self, level: str, message: str) -> None:
        color = {
            "click": "#22c55e",
            "info": "#7fb2f7",
            "warn": "#f59e0b",
            "error": "#f87171",
        }.get(level, "#a0a0a0")
        ts = time.strftime("%H:%M:%S")
        self.log_view.appendHtml(f'<span style="color:#5a5a5a">[{ts}]</span> <span style="color:{color}">{message}</span>')

    def _on_target_found(self, rect, number: int) -> None:
        self.target_label.setText(str(number))
        self.highlight.flash_at(rect, 450)

    def _on_progress(self, clicked: int, next_target: int) -> None:
        self.progress_label.setText(f"{clicked} / {self.settings.max_number}")

    def _on_finished(self, completed: bool) -> None:
        self._elapsed_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _tick_elapsed(self) -> None:
        if self._run_start_ts is None:
            return
        self.elapsed_label.setText(f"{time.monotonic() - self._run_start_ts:.2f}s")

    # ---- window lifecycle ---------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.solver.stop()
        self._pull_settings_from_ui()
        self.settings.save()
        if keyboard is not None:
            try:
                keyboard.remove_hotkey(self.settings.panic_key)
            except Exception:
                pass
        super().closeEvent(event)
