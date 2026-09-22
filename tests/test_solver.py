"""เทสต์ลูป solver กับเกมจำลอง (ไม่แตะจอ/เมาส์จริง) — รัน: .venv\\Scripts\\python.exe tests\\test_solver.py

เกมจำลองทำตัวเหมือนเกมจริง: ตาราง 5×5 เลข 1–25 สลับตำแหน่ง, กดเลขที่ถูก → ช่องนั้นกลายเป็น n+25
(หรือว่างถ้าเกิน 50) ที่เดิม และเลขต่อไป +1. เช็คทั้งความถูก (กด 1..50 ตามลำดับ) และความเร็ว —
ต้องอ่านทั้งตารางแค่ครั้งเดียว (แบบเดิมอ่านใหม่ทุกคลิก ~1.9s/คลิก ทำให้ 50 เลขกินเกินนาที)
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import capture
import mouse
import solver as solver_module
from config import MODE_GRID, Settings
from solver import Solver

GRID = (0, 0, 500, 500)
NEXT = (600, 0, 100, 100)


class FakeGame:
    def __init__(
        self, seed: int = 0, start_at: int = 1, ignore_first_click_of=(), latency_s: float = 0.0, misread=None
    ) -> None:
        self.misread = dict(misread or {})  # {เลขจริง: เลขที่ OCR อ่านผิดได้} — เฉพาะการอ่านทั้งตารางรอบแรก
        self.vote_reads = 0
        self.rows, self.cols, self.max_n = 5, 5, 50
        nums = list(range(1, 26))
        random.Random(seed).shuffle(nums)
        self.board = {(r, c): nums[r * 5 + c] for r in range(5) for c in range(5)}
        self.next = 1
        self.clicks = []
        self.click_times = []
        self.full_reads = 0
        self.next_grabs = 0
        self.ignore = set(ignore_first_click_of)
        while self.next < start_at:  # เหมือนผู้ใช้กดเองไปก่อนแล้วค่อยเปิดบอท
            self._press(next(c for c, n in self.board.items() if n == self.next))
        self.clicks.clear()
        # จอ (scrcpy) โชว์เลขต่อไปช้ากว่าเกมจริง latency_s — เก็บประวัติ (เวลา, เลขต่อไป) ไว้ย้อนดู
        self.latency_s = latency_s
        self.history = [(float("-inf"), self.next)]

    def _press(self, cell) -> None:
        n = self.board[cell]
        self.clicks.append(n)
        if n != self.next:
            return
        if n in self.ignore:  # เกมไม่รับคลิกนี้ (เช่นกดเร็วไประหว่าง animation)
            self.ignore.discard(n)
            return
        self.board[cell] = n + 25 if n + 25 <= self.max_n else None
        self.next += 1
        if hasattr(self, "history"):
            self.history.append((time.monotonic(), self.next))

    def _shown(self) -> int:
        cutoff = time.monotonic() - self.latency_s
        return [n for t, n in self.history if t <= cutoff][-1]

    # ---- ตัวแทน capture / mouse --------------------------------------------
    def grab(self, rect):
        if rect == NEXT:
            self.next_grabs += 1
            return ("next", self._shown())
        return ("grid", tuple(self.board.items()))  # ภาพตารางเปลี่ยนตามกระดาน (ใช้กับ grid_similar)

    def read_number_robust(self, img, valid_max=None, parallel=False):
        return img[1] if img[1] <= self.max_n else None  # จบเกมแล้วไม่มีเลขให้อ่าน

    def same_image(self, a, b) -> bool:
        return a == b

    def grid_similar(self, a, b, rows, cols) -> bool:
        return a == b

    def read_cells(self, grid_rect, rows, cols, cells=None, cell_pad_ratio=0.16, max_number=None):
        if cells is None:
            self.full_reads += 1
            cells = list(self.board)
        return {c: self.misread.get(self.board[c], self.board[c]) for c in cells}

    def read_cells_votes(self, grid_rect, rows, cols, cells, cell_pad_ratio=0.16):
        # อ่านซ้ำทุกรอบ OCR: รอบแรกยังผิดเหมือนเดิม รอบที่เหลืออ่านถูก — แล้วเลิกอ่านผิด
        self.vote_reads += 1
        out = {c: [self.misread.get(self.board[c], self.board[c])] + [self.board[c]] * 4 for c in cells}
        self.misread.clear()
        return out

    def click(self, x: int, y: int) -> None:
        self.click_times.append(time.monotonic())
        self._press((int(y // (GRID[3] / self.rows)), int(x // (GRID[2] / self.cols))))


def _play(game: FakeGame, confirm_timeout_s: float = 0.2, standby_steps: int = 0, between=None, **overrides):
    """standby_steps: ให้ standby อ่านตารางล่วงหน้ากี่รอบก่อนกดเริ่ม, between(game): ทำอะไรกับเกมก่อนกดเริ่ม."""
    names = ("grab", "read_number_robust", "same_image", "grid_similar", "read_cells", "read_cells_votes")
    saved = {name: getattr(capture, name) for name in names}
    saved_click, saved_timeout, saved_prepare = mouse.click, solver_module._CONFIRM_TIMEOUT_S, mouse.prepare
    for name in saved:
        setattr(capture, name, getattr(game, name))
    mouse.click = game.click
    mouse.prepare = lambda x, y: "fake click path"  # ไม่แตะมือถือ/หน้าต่างจริง
    solver_module._CONFIRM_TIMEOUT_S = confirm_timeout_s
    saved_settle, solver_module._STANDBY_SETTLE_S = solver_module._STANDBY_SETTLE_S, 0.0
    try:
        params = dict(grid_box=GRID, next_box=NEXT, max_number=50, click_delay_ms=0, poll_interval_ms=0)
        settings = Settings(**{**params, **overrides})
        bot = Solver(settings)
        done = []
        bot.finished.connect(done.append)
        for _ in range(standby_steps):
            bot._standby_step()
        if between is not None:
            between(game)
        game.run_started = time.monotonic()
        bot._run()  # รันตรงบน thread นี้เลย ไม่ต้อง start() thread แยก
        return done
    finally:
        for name, fn in saved.items():
            setattr(capture, name, fn)
        mouse.click, solver_module._CONFIRM_TIMEOUT_S, mouse.prepare = saved_click, saved_timeout, saved_prepare
        solver_module._STANDBY_SETTLE_S = saved_settle


def test_solves_all_50_in_order_with_one_full_read() -> None:
    game = FakeGame(seed=1)
    assert _play(game) == [True]
    assert game.clicks == list(range(1, 51)), game.clicks
    assert game.full_reads == 1, f"full grid reads: {game.full_reads}"


def test_starts_mid_game() -> None:
    game = FakeGame(seed=2, start_at=6)
    assert _play(game) == [True]
    assert game.clicks == list(range(6, 51)), game.clicks


def test_recovers_when_game_ignores_a_click() -> None:
    game = FakeGame(seed=3, ignore_first_click_of=(7, 31))
    assert _play(game) == [True]
    assert game.next == 51
    assert game.clicks.count(7) == 2 and game.clicks.count(31) == 2, game.clicks
    # คลิกที่ยิงล่วงหน้าตามไปก่อนจับได้ (โดนเลขผิด) ต้องไม่เกิน _MAX_IN_FLIGHT − 1 ต่อเหตุการณ์
    wasted = len(game.clicks) - 50 - 2
    assert wasted <= 2 * (solver_module._MAX_IN_FLIGHT - 1), game.clicks
    # คลิกไม่ติด → ล้าง cache อ่านทั้งตารางใหม่ ครั้งละหนึ่งรอบต่อเหตุการณ์ ไม่มากกว่านั้น
    assert game.full_reads == 3, f"full grid reads: {game.full_reads}"


def test_confident_grid_misread_is_corrected_before_clicking() -> None:
    # OCR อ่านช่อง 15 เป็น 18 (ชนกับ 18 จริง) — ต้องอ่านซ้ำเฉพาะช่องที่ขัดกันแล้วกดถูกครบ ไม่กดผิดแม้แต่ครั้งเดียว
    game = FakeGame(seed=5, misread={15: 18})
    assert _play(game) == [True]
    assert game.clicks == list(range(1, 51)), game.clicks
    assert game.full_reads == 1 and game.vote_reads == 1, (game.full_reads, game.vote_reads)


def test_grid_mode_taps_all_in_order_without_next_box() -> None:
    # โหมดตารางอย่างเดียว: ไม่มีกรอบเลขต่อไปเลย (next_box=None) — อ่านตารางครั้งเดียวแล้วกดเรียงจนครบ
    game = FakeGame(seed=7)
    assert _play(game, mode=MODE_GRID, next_box=None) == [True]
    assert game.clicks == list(range(1, 51)), game.clicks
    assert game.full_reads == 1 and game.next_grabs == 0, (game.full_reads, game.next_grabs)


def test_grid_mode_mid_game_misread_and_pace() -> None:
    # เริ่มกลางเกม (เลขต่อไป 6 — รู้ได้จากตารางอย่างเดียว) + OCR อ่าน 15 เป็น 18 + เว้นจังหวะตามเวลาเป้าหมาย
    game = FakeGame(seed=8, start_at=6, misread={15: 18})
    assert _play(game, mode=MODE_GRID, next_box=None, target_total_s=2) == [True]
    assert game.clicks == list(range(6, 51)), game.clicks
    span = game.click_times[-1] - game.click_times[0]
    expected = 2 * 44 / 49  # 45 คลิก = 44 ช่วง ที่ 2/49 s ต่อช่วง
    assert abs(span - expected) < 0.2, f"first→last click took {span:.2f}s, expected ~{expected:.2f}s"


def test_standby_reads_ahead_so_start_taps_immediately() -> None:
    # ตอนว่าง standby อ่านตารางไว้แล้ว → กดเริ่มแล้วแตะเลขแรกทันที ไม่อ่านทั้งตารางซ้ำ (ทั้งสองโหมด)
    for mode, next_box in (("ocr", NEXT), (MODE_GRID, None)):
        game = FakeGame(seed=9)
        assert _play(game, standby_steps=2, mode=mode, next_box=next_box) == [True]
        assert game.clicks == list(range(1, 51)), game.clicks
        assert game.full_reads == 1, f"{mode}: full grid reads {game.full_reads}"
        delay = game.click_times[0] - game.run_started
        assert delay < 0.05, f"{mode}: แตะแรกช้า {delay * 1000:.0f}ms หลังกดเริ่ม"


def test_standby_result_dropped_when_board_changed_before_start() -> None:
    # standby อ่านไว้ แล้วผู้ใช้กดเลข 1 เองก่อนกดเริ่ม → ตารางเปลี่ยน ต้องอ่านใหม่ ห้ามใช้ผลเก่า
    game = FakeGame(seed=10)
    press_one = lambda g: g._press(next(c for c, n in g.board.items() if n == 1))
    assert _play(game, standby_steps=2, between=press_one) == [True]
    assert game.clicks == list(range(1, 51)), game.clicks  # เลข 1 คือที่ผู้ใช้กดเอง
    assert game.full_reads == 2, f"full grid reads {game.full_reads}"


def test_standby_does_not_reocr_an_unreadable_still_image() -> None:
    # ภาพนิ่งที่อ่านไม่ออก (เช่นเกมอื่นเต็มจอทับตาราง) ต้อง OCR แค่ครั้งเดียว ไม่ใช่ทุกรอบ standby
    # (วัดจริงตอน Valorant เต็มจอ ก่อนแก้: 2 ครั้งใน 3 วินาที = กิน CPU ระหว่างเล่นเกม)
    game = FakeGame(seed=11)
    game.read_cells = lambda *a, **k: (setattr(game, "full_reads", game.full_reads + 1),
                                       {c: None for c in game.board})[1]
    game.read_number_robust = lambda *a, **k: None
    names = ("grab", "read_number_robust", "grid_similar", "read_cells", "read_cells_votes")
    saved = {n: getattr(capture, n) for n in names}
    saved_prepare, saved_settle = mouse.prepare, solver_module._STANDBY_SETTLE_S
    for n in names:
        setattr(capture, n, getattr(game, n))
    mouse.prepare, solver_module._STANDBY_SETTLE_S = (lambda x, y: "fake"), 0.0
    try:
        bot = Solver(Settings(grid_box=GRID, next_box=NEXT, max_number=50))
        for _ in range(10):
            bot._standby_step()
        assert game.full_reads == 1 and bot._prepared is None, game.full_reads
        press_one = next(c for c, n in game.board.items() if n == 1)
        game._press(press_one)  # ภาพเปลี่ยน → ลองอ่านใหม่ได้อีกครั้ง
        for _ in range(3):
            bot._standby_step()
        assert game.full_reads == 2, game.full_reads
    finally:
        for n, fn in saved.items():
            setattr(capture, n, fn)
        mouse.prepare, solver_module._STANDBY_SETTLE_S = saved_prepare, saved_settle


def test_keeps_pace_despite_display_latency() -> None:
    # จอโชว์เลขช้ากว่าเกม 150ms (เหมือน scrcpy + OCR) — แบบเดิมที่รอจอยืนยันทีละคลิกจะใช้ ≥ 49×0.15 = 7.4s
    # แต่แบบยิงล่วงหน้าต้องจบตามเวลาเป้าหมาย 4s (82ms/คลิก) — เลขสุดท้ายรอยืนยันครบก่อน จึงบวกได้ ~1 latency
    game = FakeGame(seed=6, latency_s=0.15)
    assert _play(game, confirm_timeout_s=1.0, target_total_s=4) == [True]
    assert game.clicks == list(range(1, 51)), game.clicks
    span = game.click_times[-1] - game.click_times[0]
    assert 3.9 <= span <= 4.4, f"first→last click took {span:.2f}s, expected ~4s"


def test_target_total_time_paces_clicks() -> None:
    # ตั้ง 2 วินาที → คลิกแรกถึงคลิกสุดท้ายต้อง ~2s และเว้นจังหวะเท่าๆ กัน (2/49 ≈ 41ms) ไม่ใช่กดรวดเดียว
    game = FakeGame(seed=4)
    assert _play(game, target_total_s=2) == [True]
    assert game.clicks == list(range(1, 51))
    span = game.click_times[-1] - game.click_times[0]
    assert 1.9 <= span <= 2.2, f"first→last click took {span:.2f}s, expected ~2s"
    gaps = [b - a for a, b in zip(game.click_times, game.click_times[1:])]
    assert min(gaps) >= 0.03, f"clicks bunched up: min gap {min(gaps) * 1000:.0f}ms"


if __name__ == "__main__":
    test_solves_all_50_in_order_with_one_full_read()
    test_starts_mid_game()
    test_recovers_when_game_ignores_a_click()
    test_target_total_time_paces_clicks()
    test_confident_grid_misread_is_corrected_before_clicking()
    test_grid_mode_taps_all_in_order_without_next_box()
    test_grid_mode_mid_game_misread_and_pace()
    test_standby_reads_ahead_so_start_taps_immediately()
    test_standby_result_dropped_when_board_changed_before_start()
    test_standby_does_not_reocr_an_unreadable_still_image()
    test_keeps_pace_despite_display_latency()
    print("test_solver.py OK")
