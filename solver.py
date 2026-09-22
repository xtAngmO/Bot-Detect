"""ลูปแก้เกมเรียงเลขอัตโนมัติ — อ่าน "เลขต่อไป" แล้วหา/คลิกในตาราง วนจนครบ max_number

รันบน thread แยก แล้วสื่อสารกลับ UI ผ่าน Qt signal (thread-safe ตามกลไกของ Qt เอง —
สัญญาณที่ยิงจาก thread อื่นจะถูกคิวไปประมวลผลบน thread ของตัวรับสัญญาณอัตโนมัติ)

ความเร็ว: OCR หนึ่งครั้ง ~77ms เลยห้ามอ่านทั้ง 25 ช่องใหม่ทุกคลิก (แบบเดิม ~2.5s/คลิก) —
- จำเลขของทุกช่องไว้ใน cache: เกมนี้ไม่สลับตำแหน่ง กดเลข n แล้วช่องนั้นกลายเป็นเลขใหม่ที่เดิม
  (n+25) หรือว่าง ช่องที่เพิ่งกดจึงเป็นช่องเดียวที่ต้องอ่านใหม่ และอ่านเฉพาะตอนหาเลขใน cache ไม่เจอ
- ยืนยันว่าคลิกติดด้วยการเฝ้ากรอบเลขต่อไปจนเป็น target+1 (OCR เฉพาะตอนภาพเปลี่ยน) แทนการนอนรอตายตัว
- อะไรผิดคาด (คลิกแล้วเกมไม่ขยับ / หาเลขไม่เจอ) → ล้าง cache อ่านทั้งตารางใหม่ (ขนาน ~0.3s)
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Set

from PySide6.QtCore import QObject, Signal

import capture
from capture import Cell
from config import Rect, Settings
from screenmap import ScreenMap

# รอให้เลขต่อไปขยับหลังคลิกนานสุดเท่านี้ ก่อนสรุปว่าคลิกไม่ติด แล้วอ่านตารางใหม่ทั้งหมด
_CONFIRM_TIMEOUT_S = 1.5


class Solver(QObject):
    log = Signal(str, str)  # (level: info|click|warn|error, message)
    target_found = Signal(object, int)  # (cell_rect_abs: tuple, number) — ก่อนคลิกจริง เอาไปแฟลชวงไฮไลต์
    progress = Signal(int, int)  # (clicked_count, target_number_next)
    finished = Signal(bool)  # True = ครบแล้วจบเอง, False = ถูกหยุด/พัง

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._grid_map = ScreenMap()
        self._next_map = ScreenMap()

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # settings เก็บพิกัด Qt (logical) — จับ scale ของจอไว้ตรงนี้ (GUI thread) แล้วให้ลูปแปลงเป็น
        # physical ก่อนจับภาพ/คลิก ดูเหตุผลใน screenmap.py
        if self.settings.grid_box:
            self._grid_map = ScreenMap.for_rect(self.settings.grid_box)
        if self.settings.next_box:
            self._next_map = ScreenMap.for_rect(self.settings.next_box)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- main loop -----------------------------------------------------------
    def _run(self) -> None:
        s = self.settings
        if not s.grid_box or not s.next_box:
            self.log.emit("error", "ยังไม่ได้ตั้งกรอบตาราง/กรอบเลขต่อไป")
            self.finished.emit(False)
            return

        clicked = 0
        consecutive_miss = 0
        target: Optional[int] = None  # None = ยังไม่รู้ ต้องอ่านจากกรอบเลขต่อไป
        cells: Dict[Cell, Optional[int]] = {}  # cache เลขของแต่ละช่อง
        stale: Set[Cell] = set()  # ช่องที่เพิ่งกด เลขใหม่ยังไม่ได้อ่าน
        # เว้นจังหวะให้ทั้งเกม (คลิกแรก→คลิกสุดท้าย) ใช้เวลา ~target_total_s: คลิกที่ k นัดไว้ที่
        # คลิกแรก + k × pace — นับจากนัด ไม่ใช่นอนเท่ากันทุกคลิก จึงไม่เพี้ยนตามความเร็ว OCR/เกม
        # (คลิกไหนช้า คลิกถัดไปจะไม่รอจนกว่าจะตามนัดทัน)
        pace_s = s.target_total_s / (s.max_number - 1) if s.target_total_s > 0 and s.max_number > 1 else 0.0
        first_click_at: Optional[float] = None
        self.log.emit("info", "เริ่มอัตโนมัติ")

        while not self._stop_event.is_set():
            if target is None:
                target = self._read_next_target()
                if target is None:
                    self.log.emit("warn", "อ่านเลขต่อไปไม่ออก รอบถัดไป")
                    if self._sleep(s.poll_interval_ms):
                        break
                    continue
                if target > s.max_number:
                    self.log.emit("click", f"ครบ {s.max_number} เลขแล้ว จบงาน")
                    self.finished.emit(True)
                    return

            try:
                cell = self._locate(target, cells, stale)
            except Exception as exc:  # pragma: no cover — เอาไว้กันบอทตายเงียบ
                self.log.emit("error", f"จับภาพตารางพลาด: {exc}")
                if self._sleep(s.poll_interval_ms):
                    break
                continue

            if cell is None:
                consecutive_miss += 1
                self.log.emit("info", f"ยังไม่เจอเลข {target} ในตาราง ({consecutive_miss})")
                if consecutive_miss >= s.max_consecutive_miss:
                    self.log.emit("error", f"หาเลข {target} ไม่เจอติดกัน {consecutive_miss} ครั้ง หยุดเพื่อความปลอดภัย")
                    self.finished.emit(False)
                    return
                target = None  # อ่านเลขต่อไปใหม่ด้วย เผื่อ target ที่ถืออยู่ไม่ตรงกับเกมแล้ว
                if self._sleep(s.poll_interval_ms):
                    break
                continue
            consecutive_miss = 0

            if first_click_at is not None and pace_s:
                due = first_click_at + clicked * pace_s
                if self._sleep(max(0.0, due - time.monotonic()) * 1000):
                    break

            cx, cy = capture.cell_center(self._grid_map.to_physical(s.grid_box), s.rows, s.cols, cell)
            self.target_found.emit(self._logical_cell_rect(cx, cy), target)
            self.log.emit("click", f"กดเลข {target} ที่ ({cx}, {cy})")

            import mouse  # local import กันปัญหา import ตอนเทสต์ที่ mock mouse

            before = capture.grab(self._next_map.to_physical(s.next_box))
            if first_click_at is None:
                first_click_at = time.monotonic()
            mouse.click(cx, cy)
            if self._sleep(s.click_delay_ms):
                break

            if not self._wait_for_advance(target, before):
                if self._stop_event.is_set():
                    break
                self.log.emit("warn", f"กดเลข {target} แล้วเกมไม่ขยับ — อ่านตารางใหม่ทั้งหมด")
                cells.clear()
                stale.clear()
                target = None
                continue

            clicked += 1
            cells.pop(cell, None)
            stale.add(cell)
            self.progress.emit(clicked, target + 1)
            if target >= s.max_number:
                self.log.emit("click", f"ครบ {s.max_number} เลขแล้ว จบงาน")
                self.finished.emit(True)
                return
            target += 1

        self.log.emit("warn", "หยุดแล้ว (panic key หรือกดหยุดเอง)")
        self.finished.emit(False)

    def _locate(self, target: int, cells: Dict[Cell, Optional[int]], stale: Set[Cell]) -> Optional[Cell]:
        """หาช่องของ target จาก cache ก่อน → ไม่เจอค่อยอ่านเฉพาะช่องที่เพิ่งกด → ยังไม่เจอค่อยอ่านทั้งตาราง."""
        s = self.settings
        grid_rect = self._grid_map.to_physical(s.grid_box)

        def find() -> Optional[Cell]:
            return next((c for c, n in cells.items() if n == target), None)

        cell = find()
        if cell is None and stale:
            cells.update(capture.read_cells(grid_rect, s.rows, s.cols, sorted(stale), max_number=s.max_number))
            stale.clear()
            cell = find()
        if cell is None:
            cells.clear()
            stale.clear()
            cells.update(capture.read_cells(grid_rect, s.rows, s.cols, max_number=s.max_number))
            cell = find()
        return cell

    def _wait_for_advance(self, target: int, before) -> bool:
        """รอจนกรอบเลขต่อไปกลายเป็น target+1 (= เกมรับคลิกแล้ว) — grab ถี่ๆ (~17ms) แต่ OCR (~77ms)
        เฉพาะตอนภาพเปลี่ยนจริง. เลขสุดท้ายแค่ไม่ใช่ target ก็พอ (เกมอาจขึ้นหน้าจบ ไม่มีเลขให้อ่าน)."""
        s = self.settings
        last = before
        deadline = time.monotonic() + _CONFIRM_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False
            img = capture.grab(self._next_map.to_physical(s.next_box))
            if capture.same_image(img, last):
                time.sleep(0.005)
                continue
            last = img
            n = capture.read_number_robust(img, valid_max=s.max_number, parallel=True)
            if n == target + 1 or (target >= s.max_number and n != target):
                return True
        return False

    def _logical_cell_rect(self, cx: int, cy: int) -> Rect:
        """กรอบช่องรอบจุดคลิก (physical) เป็น logical px สำหรับวงไฮไลต์ซึ่งเป็นหน้าต่าง Qt."""
        s = self.settings
        lx, ly = self._grid_map.point_to_logical(cx, cy)
        cell_w = s.grid_box[2] / s.cols
        cell_h = s.grid_box[3] / s.rows
        return (int(lx - cell_w / 2), int(ly - cell_h / 2), int(cell_w), int(cell_h))

    def _read_next_target(self) -> int | None:
        img = capture.grab(self._next_map.to_physical(self.settings.next_box))
        return capture.read_number_robust(img, valid_max=self.settings.max_number, parallel=True)

    def _sleep(self, ms: int) -> bool:
        """นอนแบบเช็ค stop event เป็นช่วงๆ — คืน True ถ้าโดนสั่งหยุดระหว่างนอน."""
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            if self._stop_event.is_set():
                return True
            time.sleep(min(0.05, end - time.monotonic()))
        return self._stop_event.is_set()
