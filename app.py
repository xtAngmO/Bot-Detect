"""หน้าต่างควบคุมหลักของ Number Sequence Bot (PySide6) — หน้าตาแบบ bot_detect_word (ดู theme.py / widgets.py)."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import capture
import theme
from config import MODE_GRID, MODE_OCR, Settings
from overlay import FrameOverlay, HighlightRing
from solver import Solver
from theme import PALETTE, SP
from widgets import Section, Segmented, Stat, StatDot, button, hline, set_button, setting_row

try:
    import keyboard  # global hotkey (panic key) — ต้องรันแบบ Administrator บางเครื่อง
except Exception:  # pragma: no cover — เครื่องที่ยังไม่ได้ pip install
    keyboard = None

_TITLE = "Number Sequence Bot — บอทเรียงเลข"
_MODE_NOTE = {
    MODE_OCR: "ใช้ 2 กรอบ (ตาราง + เลขต่อไป) — กดล่วงหน้าแล้วเช็คจากเกมทุกคลิก แตะไหนไม่ติดก็อ่านใหม่แล้วแก้เอง",
    MODE_GRID: "ใช้แค่กรอบตาราง — อ่านครั้งเดียวแล้วกดเรียงต่อเนื่อง เร็วสุด แต่ไม่เช็คว่าเกมรับแตะหรือเปล่า",
}
_MODE_NAME = {MODE_OCR: "OCR 2 กรอบ", MODE_GRID: "ตารางอย่างเดียว"}
_LOG_COLOR = {"click": "green", "info": "log-act", "warn": "amber", "error": "log-err"}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        theme.apply(QApplication.instance())
        self.setWindowTitle(_TITLE)
        self.resize(460, 900)
        self.setMinimumWidth(400)

        self.settings = Settings.load()
        capture.configure_tesseract(self.settings.tesseract_cmd)

        self.solver = Solver(self.settings)  # ก่อน overlay — callback ของกรอบเรียก solver.refresh_maps()
        self.solver.log.connect(self._on_log)
        self.solver.target_found.connect(self._on_target_found)
        self.solver.progress.connect(self._on_progress)
        self.solver.finished.connect(self._on_finished)
        self.solver.ready.connect(self._on_ready)

        self.grid_overlay = FrameOverlay("กรอบตาราง 5×5", "#22c55e", on_change=self._on_grid_change)
        self.next_overlay = FrameOverlay("กรอบเลขต่อไป", "#3b82f6", on_change=self._on_next_change)
        self._restore_overlay_geometry()
        self.highlight = HighlightRing()

        self._running = False  # ฝั่ง UI: กดเริ่มแล้วยังไม่ได้ finished (thread อาจยังไม่ขึ้น/ยังไม่จบ)
        self._run_start_ts: float | None = None
        self._current_target: int | None = None
        self._last_error = ""
        self._log_lines = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._build_ui()
        self._register_panic_key()
        # ตอนว่าง: ต่อมือถือ + อ่านตารางไว้ล่วงหน้า ให้กดเริ่มแล้วแตะเลขแรกได้ทันที
        self.solver.refresh_maps()
        self.solver.start_standby()

    # ---- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_topbar())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_control())
        col.addWidget(self._build_mode())
        col.addWidget(self._build_frames())
        col.addWidget(self._build_settings())
        col.addWidget(self._build_log(), 1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.setCentralWidget(root)

        self._apply_mode()
        self._set_status("idle")

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(SP(5), 0, SP(5), 0)
        lay.setSpacing(SP(3))
        name = QLabel("Number Sequence Bot")
        name.setObjectName("appName")
        lay.addWidget(name)
        meta = QLabel("config.json")
        meta.setObjectName("meta")
        meta.setFont(theme.mono_font(theme.T_MICRO))
        lay.addWidget(meta, 1)
        kbd = QLabel(f"{self.settings.panic_key.upper()} = หยุดฉุกเฉิน")
        kbd.setObjectName("kbd")
        kbd.setFont(theme.mono_font(theme.T_MICRO, mix=True))
        kbd.setToolTip("กดได้ทุกเมื่อ แม้โฟกัสอยู่หน้าต่างอื่น")
        kbd.setFixedHeight(22)
        lay.addWidget(kbd, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _build_control(self) -> QWidget:
        sec = Section("ควบคุม")
        self.control_section = sec
        self.status = StatDot()
        sec.body.addWidget(self.status)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("detail")
        self.detail_label.setWordWrap(True)
        sec.body.addWidget(self.detail_label)

        self.run_btn = button("เริ่มอัตโนมัติ", "play", "primary", run=True)
        self.run_btn.clicked.connect(self._on_run_clicked)
        sec.body.addSpacing(SP(1))
        sec.body.addWidget(self.run_btn)
        self.ready_label = QLabel()  # standby อ่านตารางไว้แล้วหรือยัง
        self.ready_label.setObjectName("ready")
        sec.body.addWidget(self.ready_label)

        sec.body.addWidget(hline("hair"))
        stats = QHBoxLayout()
        stats.setSpacing(SP(4))
        self.stat_next = Stat("เลขต่อไป")
        self.stat_done = Stat("กดแล้ว", f"0/{self.settings.max_number}")
        self.stat_time = Stat("เวลา", "0.00s")
        for s in (self.stat_next, self.stat_done, self.stat_time):
            stats.addWidget(s, 1)
        sec.body.addLayout(stats)
        return sec

    def _build_mode(self) -> QWidget:
        sec = Section("โหมด")
        self.mode_section = sec
        self.mode_seg = Segmented([
            (_MODE_NAME[MODE_OCR], MODE_OCR, "scan-search"),
            (_MODE_NAME[MODE_GRID], MODE_GRID, "layout-grid"),
        ])
        self.mode_seg.set_value(self.settings.mode if self.settings.mode in _MODE_NAME else MODE_OCR)
        self.mode_seg.changed.connect(self._on_mode_change)
        sec.body.addWidget(self.mode_seg)
        self.mode_note = QLabel()
        self.mode_note.setObjectName("note")
        self.mode_note.setWordWrap(True)
        sec.body.addWidget(self.mode_note)
        return sec

    def _build_frames(self) -> QWidget:
        sec = Section("กรอบบนจอ", "ลากขอบ = ย้าย · มุมขวาล่าง = ย่อ/ขยาย")
        self.grid_toggle = button("", "eye")
        self.grid_toggle.clicked.connect(self._toggle_grid_overlay)
        self.grid_status = QLabel()
        self.next_toggle = button("", "eye")
        self.next_toggle.clicked.connect(self._toggle_next_overlay)
        self.next_status = QLabel()
        for btn, status in ((self.grid_toggle, self.grid_status), (self.next_toggle, self.next_status)):
            status.setObjectName("meta")
            status.setFont(theme.mono_font(theme.T_MICRO, mix=True))
            row = QHBoxLayout()
            row.setSpacing(SP(3))
            row.addWidget(btn)
            row.addWidget(status, 1)
            sec.body.addLayout(row)
        return sec

    def _spin(self, lo: int, hi: int, value: int, step: int = 1, width: int = 96) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setFixedWidth(width)
        spin.setFont(theme.mono_font(theme.T_BODY))
        return spin

    def _build_settings(self) -> QWidget:
        sec = Section("ตาราง และ จังหวะ")
        s = self.settings
        self.rows_spin = self._spin(1, 20, s.rows, width=64)
        self.cols_spin = self._spin(1, 20, s.cols, width=64)
        self.max_spin = self._spin(1, 400, s.max_number)
        # เวลาจากคลิกแรกถึงคลิกสุดท้าย — บอทเว้นจังหวะคลิกให้เท่ากันเอง (0 = เร็วสุดเท่าที่ทำได้)
        self.target_time_spin = self._spin(0, 600, s.target_total_s)
        self.target_time_spin.setSpecialValueText("เร็วสุด")
        self.delay_spin = self._spin(0, 5000, s.click_delay_ms, step=50)
        self.poll_spin = self._spin(50, 5000, s.poll_interval_ms, step=50)
        sec.body.addWidget(setting_row("แถว × คอลัมน์", self.rows_spin, self.cols_spin))
        sec.body.addWidget(setting_row("เลขสูงสุด", self.max_spin))
        sec.body.addWidget(setting_row("เวลาเป้าหมาย (วินาที)", self.target_time_spin,
                                       note="เวลาจากแตะแรกถึงแตะสุดท้าย · 0 = เร็วสุด"))
        sec.body.addWidget(setting_row("หน่วงหลังคลิก (ms)", self.delay_spin))
        sec.body.addWidget(setting_row("รอบตรวจซ้ำ (ms)", self.poll_spin))
        # อัปเดต settings ทันทีที่แก้ (ตอนว่าง) — standby อ่านตารางล่วงหน้าด้วยค่าที่จะใช้จริงตอนกดเริ่ม
        for spin in (self.rows_spin, self.cols_spin, self.max_spin, self.target_time_spin, self.delay_spin,
                     self.poll_spin):
            spin.valueChanged.connect(self._on_setting_edited)
        return sec

    def _build_log(self) -> QWidget:
        sec = Section("บันทึกการทำงาน", "0 บรรทัด")
        self.log_section = sec
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logBox")
        self.log_view.setReadOnly(True)
        self.log_view.setFont(theme.mono_font(theme.T_LOG, mix=True))
        self.log_view.setMinimumHeight(200)
        sec.body.addWidget(self.log_view, 1)
        clear = button("ล้างบันทึก", "eraser", "ghost")
        clear.clicked.connect(self._clear_log)
        sec.body.addWidget(clear)
        return sec

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
        self.solver.refresh_maps()
        self._refresh_frame_labels()

    def _on_next_change(self, rect) -> None:
        self.settings.next_box = rect
        self.solver.refresh_maps()
        self._refresh_frame_labels()

    def _refresh_frame_labels(self) -> None:
        if not hasattr(self, "grid_toggle"):  # overlay ขยับตอนสร้างหน้าต่าง ก่อน UI พร้อม
            return
        for btn, overlay, name in ((self.grid_toggle, self.grid_overlay, "กรอบตาราง"),
                                   (self.next_toggle, self.next_overlay, "กรอบเลขต่อไป")):
            shown = overlay.isVisible()
            set_button(btn, "", "eye-off" if shown else "eye", ("ซ่อน" if shown else "แสดง") + name)
        box = self.settings.grid_box
        self.grid_status.setText(f"{box[2]} × {box[3]} px @ {box[0]},{box[1]}" if box else "ยังไม่ตั้งกรอบ")
        if self.settings.mode == MODE_GRID:
            self.next_status.setText("ไม่ใช้ในโหมดตารางอย่างเดียว")
        else:
            box = self.settings.next_box
            self.next_status.setText(f"{box[2]} × {box[3]} px @ {box[0]},{box[1]}" if box else "ยังไม่ตั้งกรอบ")

    def _on_mode_change(self, mode) -> None:
        self.settings.mode = mode
        self._apply_mode()

    def _apply_mode(self) -> None:
        """โหมดตารางอย่างเดียวไม่ใช้กรอบเลขต่อไป — ซ่อนกรอบนั้นและปิดปุ่ม กันผู้ใช้งงว่าต้องลากไหม."""
        grid_only = self.settings.mode == MODE_GRID
        self.next_toggle.setEnabled(not grid_only)
        if grid_only:
            self.next_overlay.hide()
        self.mode_note.setText(_MODE_NOTE[MODE_GRID if grid_only else MODE_OCR])
        self.control_section.meta.setText(_MODE_NAME[MODE_GRID if grid_only else MODE_OCR])
        self._refresh_frame_labels()

    def _toggle_grid_overlay(self) -> None:
        self.grid_overlay.setVisible(not self.grid_overlay.isVisible())
        self._refresh_frame_labels()

    def _toggle_next_overlay(self) -> None:
        self.next_overlay.setVisible(not self.next_overlay.isVisible())
        self._refresh_frame_labels()

    # ---- start/stop ------------------------------------------------------------
    def _on_setting_edited(self) -> None:
        if not self._running:  # ระหว่างรันห้ามเปลี่ยนค่าที่ลูปกำลังใช้อยู่ — มีผลรอบหน้า
            self._pull_settings_from_ui()

    def _pull_settings_from_ui(self) -> None:
        self.settings.rows = self.rows_spin.value()
        self.settings.cols = self.cols_spin.value()
        self.settings.max_number = self.max_spin.value()
        self.settings.target_total_s = self.target_time_spin.value()
        self.settings.click_delay_ms = self.delay_spin.value()
        self.settings.poll_interval_ms = self.poll_spin.value()
        self.settings.mode = self.mode_seg.value()

    def _on_run_clicked(self) -> None:
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        self._pull_settings_from_ui()
        if self.settings.mode == MODE_GRID:
            if not self.settings.grid_box:
                QMessageBox.warning(self, "ยังไม่พร้อม", "ตั้งกรอบตารางก่อนเริ่มอัตโนมัติ")
                return
        elif not self.settings.grid_box or not self.settings.next_box:
            QMessageBox.warning(self, "ยังไม่พร้อม", "ตั้งกรอบตารางและกรอบเลขต่อไปก่อนเริ่มอัตโนมัติ")
            return
        self.settings.save()
        self._running = True
        self._run_start_ts = time.monotonic()
        self._current_target = None
        self._last_error = ""
        self._elapsed_timer.start()
        self.ready_label.clear()
        self.stat_next.set("—")
        self.stat_done.set(f"0/{self.settings.max_number}")
        self.mode_seg.setEnabled(False)
        set_button(self.run_btn, "stop", "square", "หยุด")
        self._set_status("starting")
        self.setWindowTitle("▶ กำลังทำงาน — " + _TITLE)
        self.solver.start()

    def _stop(self) -> None:
        self.solver.stop()
        if self._running:
            self.detail_label.setText("กำลังหยุด…")

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

    # ---- status ------------------------------------------------------------------
    def _elapsed(self) -> float:
        return time.monotonic() - self._run_start_ts if self._run_start_ts is not None else 0.0

    def _set_status(self, state: str) -> None:
        """state: idle | starting | running | done | stopped | error — บรรทัดใหญ่ + รายละเอียดใต้บรรทัด."""
        took = f"{self._elapsed():.2f}s"
        head, detail = {
            "idle": ("ว่าง", f"กด เริ่มอัตโนมัติ เมื่อกรอบพร้อม · {self.settings.panic_key.upper()} หยุดได้ทุกเมื่อ"),
            "starting": ("กำลังเริ่ม…", "เตรียมมือถือ / อ่านตาราง"),
            "running": ("กำลังทำงาน", f"กดเลข {self._current_target} · {self._elapsed():.1f}s"),
            "done": ("เสร็จแล้ว", f"กดครบถึงเลข {self.settings.max_number} · ใช้เวลา {took}"),
            "stopped": ("หยุดอยู่", f"หยุดเอง (ปุ่มหยุด / {self.settings.panic_key.upper()}) · "
                                    f"ถึงเลข {self._current_target or '—'} · {took}"),
            "error": ("หยุดเพราะมีปัญหา", self._last_error),
        }[state]
        if self.status.state() != state or self.status.text() != head:
            self.status.set_state(state, head)
        self.detail_label.setText(detail)
        if self.detail_label.property("state") != state:
            self.detail_label.setProperty("state", state)
            self.detail_label.style().unpolish(self.detail_label)
            self.detail_label.style().polish(self.detail_label)

    def _on_ready(self, text: str) -> None:
        if not self._running:
            self.ready_label.setText(text)

    # ---- solver signal handlers ------------------------------------------------
    def _on_log(self, level: str, message: str) -> None:
        if level == "error":
            self._last_error = message
        color = PALETTE[_LOG_COLOR.get(level, "text-dim")]
        ts = time.strftime("%H:%M:%S")
        self.log_view.appendHtml(
            f'<span style="color:{PALETTE["text-faint"]}">{ts}</span>&nbsp;&nbsp;'
            f'<span style="color:{color}">{html.escape(message)}</span>'
        )
        self._log_lines += 1
        self.log_section.meta.setText(f"{self._log_lines} บรรทัด")

    def _clear_log(self) -> None:
        self.log_view.clear()
        self._log_lines = 0
        self.log_section.meta.setText("0 บรรทัด")

    def _on_target_found(self, rect, number: int) -> None:
        self.stat_next.set(str(number))
        self.highlight.flash_at(rect, 450)
        self._current_target = number
        self._set_status("running")

    def _on_progress(self, clicked: int, next_target: int) -> None:
        self.stat_done.set(f"{clicked}/{self.settings.max_number}")

    def _on_finished(self, completed: bool) -> None:
        self._running = False
        self._elapsed_timer.stop()
        self._tick_elapsed()
        self.mode_seg.setEnabled(True)
        set_button(self.run_btn, "primary", "play", "เริ่มอัตโนมัติ")
        self.setWindowTitle(_TITLE)
        self._set_status("done" if completed else ("error" if self._last_error else "stopped"))

    def _tick_elapsed(self) -> None:
        if self._run_start_ts is None:
            return
        self.stat_time.set(f"{self._elapsed():.2f}s")
        if self._running and self._current_target is not None:
            self._set_status("running")

    # ---- window lifecycle ---------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.solver.stop()
        self.solver.stop_standby()
        self._pull_settings_from_ui()
        self.settings.save()
        if keyboard is not None:
            try:
                keyboard.remove_hotkey(self.settings.panic_key)
            except Exception:
                pass
        super().closeEvent(event)
