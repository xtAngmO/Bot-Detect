"""ลูปแก้เกมเรียงเลขอัตโนมัติ — อ่าน "เลขต่อไป" แล้วหา/คลิกในตาราง วนจนครบ max_number

รันบน thread แยก แล้วสื่อสารกลับ UI ผ่าน Qt signal (thread-safe ตามกลไกของ Qt เอง —
สัญญาณที่ยิงจาก thread อื่นจะถูกคิวไปประมวลผลบน thread ของตัวรับสัญญาณอัตโนมัติ)

ความเร็ว (เป้า 50 เลขใน 8 วินาที = 163ms/คลิก): OCR หนึ่งครั้ง ~77ms และจอ scrcpy ตามหลังมือถือ
~0.1–0.2s ถ้ารอจอยืนยันทีละคลิกได้แค่ ~4 คลิก/วินาที จึง —
- อ่านทั้งตารางครั้งเดียวตอนเริ่ม แล้ว *ทำนาย* ตำแหน่งต่อ: เกมนี้ไม่สลับตำแหน่ง กดเลข n แล้วช่องเดิม
  กลายเป็น n + rows×cols (หรือว่าง) — ไม่ต้อง OCR ช่องซ้ำระหว่างเล่น
- `_NextWatcher` เฝ้ากรอบเลขต่อไปบน thread แยก ลูปหลักคลิกตามจังหวะไปได้เลย ปล่อยให้มีคลิกที่จอยังไม่
  ยืนยันค้างได้ไม่เกิน `_MAX_IN_FLIGHT` (เลขสุดท้ายรอยืนยันครบก่อน เพื่อเช็คจบเกมได้แน่นอน)
- อะไรผิดคาด (คลิกค้างไม่ยืนยันเกิน `_CONFIRM_TIMEOUT_S` / หาเลขไม่เจอ) → อ่านเลขต่อไป + ทั้งตารางใหม่

ความแม่น: ทุกครั้งที่อ่านทั้งตาราง (`_sync`) ไม่เชื่อ OCR ทีละช่อง แต่ให้ `gridsolve` จับคู่กับชุดเลขที่ตาราง
ต้องมีตามกติกาเกม ช่องที่ผลขัดกันอ่านซ้ำทุกรอบ OCR แล้วแก้ใหม่ — ดู gridsolve.py
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QObject, Signal

import capture
import gridsolve
from capture import Cell
from config import MODE_GRID, Rect, Settings
from screenmap import ScreenMap

# คลิกที่ยิงไปแล้วแต่จอยังไม่ยืนยัน ค้างได้สูงสุดเท่านี้ — ที่ 163ms/คลิก รับความหน่วงรวม (มือถือ + scrcpy +
# OCR) ได้ถึง ~0.49s โดยไม่ช้าลง. ถ้าเกมไม่รับคลิกไหน คลิกที่ยิงตามไปก่อนระบบจับได้จะโดนเลขผิดไม่เกิน 2 ครั้ง
_MAX_IN_FLIGHT = 3
# คลิกเก่าสุดที่ยังไม่ยืนยันค้างนานเกินนี้ = เกมไม่รับคลิก → อ่านตารางใหม่ทั้งหมด (self-healing)
_CONFIRM_TIMEOUT_S = 1.5
# เตรียมพร้อมตอนว่าง (ก่อนกดเริ่ม): จับภาพตารางทุก _STANDBY_POLL_S แล้ว OCR ล่วงหน้าเมื่อภาพนิ่งครบ
# _STANDBY_SETTLE_S และต่างจากที่อ่านไว้ — ภาพที่ไม่เคยนิ่ง (เช่นเกมอื่นเต็มจอทับอยู่) จะไม่ถูก OCR เลย
_STANDBY_POLL_S = 0.15
_STANDBY_SETTLE_S = 0.3


@dataclass
class _Prepared:
    """ผลอ่านตารางล่วงหน้า — ใช้ได้เมื่อค่าตั้ง (key) ยังเหมือนเดิมและภาพตารางตอนกดเริ่มยังเหมือน image."""
    key: tuple
    image: object
    next: int
    where: Dict[int, Cell]


class _NextWatcher:
    """เฝ้ากรอบเลขต่อไปบน thread แยก — grab ถี่ๆ (~17ms) แต่ OCR (~77ms) เฉพาะตอนภาพเปลี่ยนจริง
    แล้วเก็บ `reading` = (เวลาที่ grab ภาพนั้น, เลขที่อ่านได้ หรือ None) ล่าสุดไว้ให้ลูปหลักอ่านแบบไม่ต้องรอ."""

    def __init__(self, rect: Rect, valid_max: int, stop_event: threading.Event) -> None:
        self._rect = rect
        self._valid_max = valid_max
        self._stop_event = stop_event
        self._closed = threading.Event()
        self.reading: Tuple[float, Optional[int]] = (0.0, None)  # แทนที่ทั้ง tuple ทีเดียว = atomic
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        last = None
        while not self._closed.is_set() and not self._stop_event.is_set():
            grabbed_at = time.monotonic()
            try:
                img = capture.grab(self._rect)
                if last is not None and capture.same_image(img, last):
                    time.sleep(0.005)
                    continue
                last = img
                n = capture.read_number_robust(img, valid_max=self._valid_max, parallel=True)
            except Exception:  # pragma: no cover — จับภาพพลาดชั่วคราว อย่าให้ thread ตายเงียบ
                time.sleep(0.05)
                continue
            self.reading = (grabbed_at, n)


class Solver(QObject):
    log = Signal(str, str)  # (level: info|click|warn|error, message)
    target_found = Signal(object, int)  # (cell_rect_abs: tuple, number) — ก่อนคลิกจริง เอาไปแฟลชวงไฮไลต์
    progress = Signal(int, int)  # (clicked_count, target_number_next)
    finished = Signal(bool)  # True = ครบแล้วจบเอง, False = ถูกหยุด/พัง
    ready = Signal(str)  # สถานะเตรียมพร้อมตอนว่าง (ว่าง = ยังไม่ได้อ่านตารางไว้) ให้ UI โชว์ใต้ปุ่มเริ่ม

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._grid_map = ScreenMap()
        self._next_map = ScreenMap()
        self._prepared: Optional[_Prepared] = None
        self._prepare_lock = threading.Lock()  # standby ถือไว้ระหว่าง OCR — กดเริ่มจะรอผลนั้นแทนอ่านซ้ำ
        self._standby_thread: threading.Thread | None = None
        self._standby_stop = threading.Event()
        self._sb_image = None  # ภาพตารางล่าสุดที่ standby เห็น + เวลาที่เริ่มนิ่ง
        self._sb_since = 0.0
        self._sb_tried: Optional[Tuple[tuple, object]] = None  # (key, ภาพ) ที่ลอง OCR ไปแล้ว — สำเร็จหรือไม่ก็ตาม

    # ---- lifecycle ---------------------------------------------------------
    def refresh_maps(self) -> None:
        """settings เก็บพิกัด Qt (logical) — จับ scale ของจอไว้ (ต้องเรียกบน GUI thread) แล้วให้ลูปแปลงเป็น
        physical ก่อนจับภาพ/คลิก ดูเหตุผลใน screenmap.py. เรียกตอนเริ่มและทุกครั้งที่กรอบขยับ."""
        if self.settings.grid_box:
            self._grid_map = ScreenMap.for_rect(self.settings.grid_box)
        if self.settings.next_box:
            self._next_map = ScreenMap.for_rect(self.settings.next_box)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.refresh_maps()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- เตรียมพร้อมตอนว่าง -----------------------------------------------------
    def start_standby(self) -> None:
        """ตอนว่าง: ต่อมือถือรอไว้ + อ่านตารางล่วงหน้า — กดเริ่มแล้วภาพตารางยังเหมือนเดิมก็แตะเลขแรกได้ทันที
        ไม่ต้องรอต่อมือถือ (~0.75s) + OCR ทั้งตาราง (~0.5s). เรียกจาก GUI หลังสร้างหน้าต่าง."""
        if self._standby_thread and self._standby_thread.is_alive():
            return
        self._standby_stop.clear()
        self._standby_thread = threading.Thread(target=self._standby_loop, daemon=True)
        self._standby_thread.start()

    def stop_standby(self) -> None:
        self._standby_stop.set()

    def _standby_loop(self) -> None:
        while not self._standby_stop.wait(_STANDBY_POLL_S):
            try:
                self._standby_step()
            except Exception:  # pragma: no cover — จับภาพ/OCR พลาดชั่วคราวตอนว่าง ไม่ต้องทำอะไร
                pass

    def _settings_key(self) -> tuple:
        s = self.settings
        next_box = None if s.mode == MODE_GRID else s.next_box
        return (s.mode, s.rows, s.cols, s.max_number, tuple(s.grid_box or ()), tuple(next_box or ()))

    def _standby_step(self) -> None:
        s = self.settings
        if self.is_running() or not s.grid_box or (s.mode != MODE_GRID and not s.next_box):
            return
        grid_rect = self._grid_map.to_physical(s.grid_box)
        img = capture.grab(grid_rect)
        now = time.monotonic()
        if self._sb_image is None or not capture.grid_similar(img, self._sb_image, s.rows, s.cols):
            self._sb_image, self._sb_since = img, now  # ภาพเพิ่งเปลี่ยน รอให้นิ่งก่อน
            return
        if now - self._sb_since < _STANDBY_SETTLE_S:
            return
        key = self._settings_key()
        tried = self._sb_tried
        # ภาพนี้ลองอ่านไปแล้ว (อ่านออกหรือไม่ก็ตาม) — ไม่งั้นภาพที่อ่านไม่ออกแต่นิ่ง (เช่นเมนูเกมอื่นเต็มจอทับอยู่)
        # จะโดน OCR ซ้ำทุก 0.3s กิน CPU ไปเรื่อยๆ (วัดจริงตอน Valorant เต็มจอ: 2 ครั้งใน 3 วินาที)
        if tried is not None and tried[0] == key and capture.grid_similar(img, tried[1], s.rows, s.cols):
            return
        self._sb_tried = (key, img)
        with self._prepare_lock:
            if self.is_running():
                return
            import mouse

            gx, gy, gw, gh = grid_rect
            mouse.prepare(gx + gw // 2, gy + gh // 2)  # ต่อมือถือรอไว้ (ต่อแล้วก็แค่เช็คว่ายังไม่หลุด)
            synced = self._sync(grid_rect, use_next_box=s.mode != MODE_GRID, quiet=True)
            if synced is None:
                self._prepared = None
                self.ready.emit("")
                return
            self._prepared = _Prepared(key, img, synced[0], synced[1])
        self.ready.emit(f"⚡ อ่านตารางไว้แล้ว — กดเริ่มได้ทันที (เลขต่อไป {synced[0]})")

    def _take_prepared(self, grid_rect: Rect) -> Optional[Tuple[int, Dict[int, Cell]]]:
        """ผลที่อ่านไว้ล่วงหน้า ถ้าค่าตั้งเหมือนเดิมและภาพตารางตอนนี้ยังเหมือนตอนอ่าน (ใช้ได้ครั้งเดียว)."""
        with self._prepare_lock:  # standby กำลัง OCR อยู่ → รอผลนั้น (เริ่มก่อน เสร็จก่อนอ่านใหม่เอง)
            p, self._prepared = self._prepared, None
        self.ready.emit("")
        s = self.settings
        if p is None or p.key != self._settings_key():
            return None
        if not capture.grid_similar(capture.grab(grid_rect), p.image, s.rows, s.cols):
            return None
        return p.next, dict(p.where)

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- main loop -----------------------------------------------------------
    def _run(self) -> None:
        s = self.settings
        grid_only = s.mode == MODE_GRID
        if not s.grid_box or (not grid_only and not s.next_box):
            self.log.emit("error", "ยังไม่ได้ตั้งกรอบตาราง" if grid_only else "ยังไม่ได้ตั้งกรอบตาราง/กรอบเลขต่อไป")
            self.finished.emit(False)
            return

        import mouse  # local import กันปัญหา import ตอนเทสต์ที่ mock mouse

        self.log.emit("info", "เริ่มอัตโนมัติ" + (" — โหมดตารางอย่างเดียว" if grid_only else " — โหมด OCR 2 กรอบ"))
        grid_rect = self._grid_map.to_physical(s.grid_box)
        gx, gy, gw, gh = grid_rect
        # ต่อมือถือก่อน ไม่ให้กินเวลาแตะแรก (standby ต่อไว้ให้แล้วก็แค่เช็คว่ายังไม่หลุด)
        self.log.emit("info", mouse.prepare(gx + gw // 2, gy + gh // 2))
        prepared = self._take_prepared(grid_rect)
        if prepared is not None:
            self.log.emit("info", f"ใช้ตารางที่อ่านไว้ล่วงหน้า — เริ่มกดทันที (เลขต่อไป {prepared[0]})")
        if grid_only:
            completed = self._solve_grid(prepared)
        else:
            watcher = _NextWatcher(self._next_map.to_physical(s.next_box), s.max_number, self._stop_event)
            watcher.start()
            try:
                completed = self._solve(watcher, prepared)
            finally:
                watcher.close()
        if completed is None:
            self.log.emit("warn", "หยุดแล้ว (panic key หรือกดหยุดเอง)")
        self.finished.emit(bool(completed))

    def _pace_s(self) -> float:
        """เว้นจังหวะให้ทั้งเกม (คลิกแรก→คลิกสุดท้าย) ใช้เวลา ~target_total_s: คลิกเลข k นัดไว้ที่ คลิกแรก +
        (k − เลขแรก) × pace — นับจากนัด ไม่ใช่นอนเท่ากันทุกคลิก จึงไม่เพี้ยนตามความเร็ว OCR/เกม."""
        s = self.settings
        return s.target_total_s / (s.max_number - 1) if s.target_total_s > 0 and s.max_number > 1 else 0.0

    def _tap(self, grid_rect: Rect, cell: Cell, number: int) -> float:
        """แฟลชวงไฮไลต์ + log แล้วคลิกกลางช่อง — คืนเวลาที่เริ่มคลิก."""
        import mouse

        s = self.settings
        cx, cy = capture.cell_center(grid_rect, s.rows, s.cols, cell)
        self.target_found.emit(self._logical_cell_rect(cx, cy), number)
        self.log.emit("click", f"กดเลข {number} ที่ ({cx}, {cy})")
        started = time.monotonic()
        mouse.click(cx, cy)
        return started

    def _solve_grid(self, prepared: Optional[Tuple[int, Dict[int, Cell]]] = None) -> Optional[bool]:
        """โหมดตารางอย่างเดียว: อ่านทั้งตารางครั้งเดียว (ตรวจทานด้วย gridsolve เหมือนโหมด OCR) แล้วกดเรียงจนครบ
        ตามจังหวะ ไม่มีกรอบเลขต่อไปให้ยืนยัน — ตำแหน่งเลขถัดๆ ไปใช้กติกาเดียวกัน (กด n แล้วช่องเดิมกลายเป็น
        n + rows×cols). คืน True = กดครบ, False = อ่านตารางไม่ได้, None = โดนสั่งหยุด."""
        s = self.settings
        grid_rect = self._grid_map.to_physical(s.grid_box)
        n_cells = s.rows * s.cols
        pace_s = self._pace_s()

        synced = prepared  # อ่านไว้ล่วงหน้าแล้ว (standby) ก็ข้ามไปกดได้เลย
        attempt = 0
        while synced is None:
            attempt += 1
            try:
                synced = self._sync(grid_rect, use_next_box=False)
            except Exception as exc:  # pragma: no cover — เอาไว้กันบอทตายเงียบ
                self.log.emit("error", f"จับภาพตารางพลาด: {exc}")
            if synced is not None:
                break
            if attempt >= s.max_consecutive_miss:
                self.log.emit("error", f"อ่านตารางไม่ได้ติดกัน {attempt} ครั้ง หยุดเพื่อความปลอดภัย")
                return False
            self.log.emit("warn", f"ยังอ่านตารางไม่ได้ ({attempt}) รอบถัดไป")
            if self._sleep(s.poll_interval_ms):
                return None

        first, where = synced
        base: Optional[float] = None
        for k in range(first, s.max_number + 1):
            if self._stop_event.is_set():
                return None
            cell = where.pop(k, None)
            if cell is None:  # ไม่ควรเกิด — gridsolve จับคู่ครบทุกเลขในชุด และเลขถัดไปทำนายจากช่องที่กดแล้ว
                self.log.emit("error", f"ไม่รู้ตำแหน่งเลข {k} หยุดเพื่อความปลอดภัย")
                return False
            if base is not None and pace_s:
                if self._sleep(max(0.0, base + (k - first) * pace_s - time.monotonic()) * 1000):
                    return None
            started = self._tap(grid_rect, cell, k)
            if base is None:
                base = started
            if k + n_cells <= s.max_number:
                where[k + n_cells] = cell
            self.progress.emit(k - first + 1, k + 1)
            if self._sleep(s.click_delay_ms):
                return None
        self.log.emit("click", f"กดครบถึงเลข {s.max_number} แล้ว (โหมดตาราง — ไม่ได้ยืนยันจากเกม)")
        return True

    def _solve(
        self, watcher: _NextWatcher, prepared: Optional[Tuple[int, Dict[int, Cell]]] = None
    ) -> Optional[bool]:
        """โหมด OCR 2 กรอบ — คืน True = ครบ, False = หยุดเพื่อความปลอดภัย, None = โดนสั่งหยุด."""
        s = self.settings
        grid_rect = self._grid_map.to_physical(s.grid_box)
        n_cells = s.rows * s.cols
        pace_s = self._pace_s()

        clicked = 0
        consecutive_miss = 0
        target: Optional[int] = None  # เลขถัดไปที่จะกด — None = ต้อง sync กับจอใหม่ก่อน
        where: Dict[int, Cell] = {}  # เลข → ช่อง (อ่านจากจอ + ทำนายหลังกด)
        if prepared is not None:  # อ่านไว้ล่วงหน้าแล้ว (standby) — ไม่ต้อง sync รอบแรก
            target, where = prepared
        confirmed = target - 1 if target is not None else 0  # เลขมากสุดที่จอยืนยันแล้วว่ากดติด
        tapped_at: Dict[int, float] = {}
        base: Optional[Tuple[float, int]] = None  # (เวลา, เลข) ของคลิกแรกหลัง sync — ตั้งนัดคลิกถัดไป

        while not self._stop_event.is_set():
            if target is None:
                try:
                    synced = self._sync(grid_rect)
                except Exception as exc:  # pragma: no cover — เอาไว้กันบอทตายเงียบ
                    self.log.emit("error", f"จับภาพตารางพลาด: {exc}")
                    synced = None
                if synced is not None:
                    target, where = synced
                    confirmed, tapped_at, base = target - 1, {}, None

            cell = where.get(target) if target is not None else None
            if cell is None:
                consecutive_miss += 1
                what = f"เลข {target} ในตาราง" if target is not None else "เลขต่อไป/ตาราง"
                self.log.emit("warn", f"ยังอ่าน{what}ไม่ได้ ({consecutive_miss}) รอบถัดไป")
                if consecutive_miss >= s.max_consecutive_miss:
                    self.log.emit("error", f"อ่าน{what}ไม่ได้ติดกัน {consecutive_miss} ครั้ง หยุดเพื่อความปลอดภัย")
                    return False
                target = None  # อ่านจอใหม่ทั้งหมด เผื่อ target ที่ถืออยู่ไม่ตรงกับเกมแล้ว
                if self._sleep(s.poll_interval_ms):
                    return None
                continue
            consecutive_miss = 0

            limit = 1 if target >= s.max_number else _MAX_IN_FLIGHT
            now_confirmed = self._catch_up(watcher, target, confirmed, tapped_at, limit)
            if now_confirmed is None:
                return None
            if now_confirmed < 0:
                self.log.emit("warn", f"กดเลข {confirmed + 1} แล้วเกมไม่ขยับ — อ่านตารางใหม่ทั้งหมด")
                target = None
                continue
            if now_confirmed > confirmed:
                clicked += now_confirmed - confirmed
                confirmed = now_confirmed
                self.progress.emit(clicked, confirmed + 1)

            if base is not None and pace_s:
                due = base[0] + (target - base[1]) * pace_s
                if self._sleep(max(0.0, due - time.monotonic()) * 1000):
                    return None

            tapped_at[target] = self._tap(grid_rect, cell, target)
            if base is None:
                base = (tapped_at[target], target)
            del where[target]
            if target + n_cells <= s.max_number:
                where[target + n_cells] = cell
            if self._sleep(s.click_delay_ms):
                return None

            if target >= s.max_number:
                done = self._await_finish(watcher, tapped_at[target])
                if done is None:
                    return None
                if not done:
                    self.log.emit("warn", f"กดเลข {target} แล้วเกมไม่ขยับ — อ่านตารางใหม่ทั้งหมด")
                    target = None
                    continue
                self.progress.emit(clicked + 1, target + 1)
                self.log.emit("click", f"ครบ {s.max_number} เลขแล้ว จบงาน")
                return True
            target += 1

        return None

    def _catch_up(
        self, watcher: _NextWatcher, target: int, confirmed: int, tapped_at: Dict[int, float], limit: int
    ) -> Optional[int]:
        """รอจนคลิกที่จอยังไม่ยืนยัน (เลข confirmed+1 .. target−1) เหลือน้อยกว่า limit แล้วคืน confirmed ใหม่.
        คืน −1 ถ้าคลิกเก่าสุดที่ยังไม่ยืนยันค้างเกิน _CONFIRM_TIMEOUT_S (เกมไม่รับ), None ถ้าโดนสั่งหยุด.
        เชื่อเลขจากจอเฉพาะช่วง confirmed+1 .. target (ไม่เกินเลขที่กดไปแล้ว +1) — OCR อ่านผิดเป็นเลขน้อยลงจะไม่
        ทำให้ถอยหลัง ส่วนอ่านผิดเป็นเลขมากขึ้นจะไปค้างที่รอบถัดไปแล้ว resync เอง."""
        while True:
            n = watcher.reading[1]
            if n is not None and confirmed + 1 < n <= target:
                confirmed = n - 1
            if target - 1 - confirmed < limit:
                return confirmed
            if self._stop_event.is_set():
                return None
            if time.monotonic() - tapped_at[confirmed + 1] > _CONFIRM_TIMEOUT_S:
                return -1
            time.sleep(0.002)

    def _await_finish(self, watcher: _NextWatcher, tapped: float) -> Optional[bool]:
        """หลังกดเลขสุดท้าย (จอยืนยันเลขก่อนหน้าครบแล้ว) — จบเมื่อภาพที่ grab หลังคลิกไม่ใช่เลขสุดท้ายแล้ว
        (เกมอาจขึ้นหน้าจบ ไม่มีเลขให้อ่าน)."""
        last = self.settings.max_number
        while time.monotonic() - tapped < _CONFIRM_TIMEOUT_S:
            if self._stop_event.is_set():
                return None
            grabbed_at, n = watcher.reading
            if grabbed_at > tapped and n != last:
                return True
            time.sleep(0.002)
        return False

    def _sync(
        self, grid_rect: Rect, use_next_box: bool = True, quiet: bool = False
    ) -> Optional[Tuple[int, Dict[int, Cell]]]:
        """อ่านจอใหม่ทั้งหมด → (เลขถัดไป, {เลข: ช่อง}) — อ่านทั้งตารางขนาน (~0.3s) แล้วให้ gridsolve จับคู่กับ
        ชุดเลขที่ตารางต้องมี ช่องที่ผลขัดกันอ่านซ้ำครบทุกรอบ OCR แล้วแก้ใหม่. None = อ่านไม่ออกเลย.
        use_next_box=False (โหมดตาราง): ไม่มีกรอบเลขต่อไป — เลขถัดไป = เลขน้อยสุดที่สอดคล้องกับตาราง.
        quiet=True (อ่านล่วงหน้าตอนว่าง): ไม่ log — ไม่ให้ log รกตอนยังไม่ได้กดเริ่ม."""
        s = self.settings
        n_cells = s.rows * s.cols
        hint = self._read_next_target() if use_next_box else None
        first = capture.read_cells(grid_rect, s.rows, s.cols, max_number=s.max_number)
        readings = {c: [n] for c, n in first.items()}
        sol = gridsolve.solve(readings, hint, n_cells, s.max_number)
        if sol is not None and sol.conflicts:
            for c, votes in capture.read_cells_votes(grid_rect, s.rows, s.cols, sorted(sol.conflicts)).items():
                readings[c] = readings[c] + votes
            sol = gridsolve.solve(readings, hint, n_cells, s.max_number)
        if sol is None or quiet:
            return None if sol is None else (sol.next, sol.where)
        if use_next_box and hint is None:
            self.log.emit("info", f"อ่านกรอบเลขต่อไปไม่ออก ใช้เลขน้อยสุดในตาราง: {sol.next}")
        elif use_next_box and hint != sol.next:
            self.log.emit("warn", f"กรอบเลขต่อไปอ่านได้ {hint} แต่ตารางบอกว่า {sol.next} — เชื่อตาราง")
        guessed = [f"{n}@{c}" for n, c in sorted(sol.where.items()) if c in sol.doubtful]
        if guessed:
            self.log.emit("warn", "ช่องที่อ่านไม่ชัด ได้เลขจากการตัดตัวเลือก: " + ", ".join(guessed))
        return sol.next, sol.where

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
            time.sleep(max(0.0, min(0.05, end - time.monotonic())))
        return self._stop_event.is_set()
