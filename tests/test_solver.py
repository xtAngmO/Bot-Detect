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
from config import Settings
from solver import Solver

GRID = (0, 0, 500, 500)
NEXT = (600, 0, 100, 100)


class FakeGame:
    def __init__(self, seed: int = 0, start_at: int = 1, ignore_first_click_of=()) -> None:
        self.rows, self.cols, self.max_n = 5, 5, 50
        nums = list(range(1, 26))
        random.Random(seed).shuffle(nums)
        self.board = {(r, c): nums[r * 5 + c] for r in range(5) for c in range(5)}
        self.next = 1
        self.clicks = []
        self.click_times = []
        self.full_reads = 0
        self.ignore = set(ignore_first_click_of)
        while self.next < start_at:  # เหมือนผู้ใช้กดเองไปก่อนแล้วค่อยเปิดบอท
            self._press(next(c for c, n in self.board.items() if n == self.next))
        self.clicks.clear()

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

    # ---- ตัวแทน capture / mouse --------------------------------------------
    def grab(self, rect):
        return ("next", self.next) if rect == NEXT else ("grid",)

    def read_number_robust(self, img, valid_max=None, parallel=False):
        return img[1] if img[1] <= self.max_n else None  # จบเกมแล้วไม่มีเลขให้อ่าน

    def same_image(self, a, b) -> bool:
        return a == b

    def read_cells(self, grid_rect, rows, cols, cells=None, cell_pad_ratio=0.16, max_number=None):
        if cells is None:
            self.full_reads += 1
            cells = list(self.board)
        return {c: self.board[c] for c in cells}

    def click(self, x: int, y: int) -> None:
        self.click_times.append(time.monotonic())
        self._press((int(y // (GRID[3] / self.rows)), int(x // (GRID[2] / self.cols))))


def _play(game: FakeGame, **overrides):
    saved = {name: getattr(capture, name) for name in ("grab", "read_number_robust", "same_image", "read_cells")}
    saved_click, saved_timeout = mouse.click, solver_module._CONFIRM_TIMEOUT_S
    for name in saved:
        setattr(capture, name, getattr(game, name))
    mouse.click = game.click
    solver_module._CONFIRM_TIMEOUT_S = 0.05
    try:
        params = dict(grid_box=GRID, next_box=NEXT, max_number=50, click_delay_ms=0, poll_interval_ms=0)
        settings = Settings(**{**params, **overrides})
        bot = Solver(settings)
        done = []
        bot.finished.connect(done.append)
        bot._run()  # รันตรงบน thread นี้เลย ไม่ต้อง start() thread แยก
        return done
    finally:
        for name, fn in saved.items():
            setattr(capture, name, fn)
        mouse.click, solver_module._CONFIRM_TIMEOUT_S = saved_click, saved_timeout


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
    # คลิกไม่ติด → ล้าง cache อ่านทั้งตารางใหม่ ครั้งละหนึ่งรอบต่อเหตุการณ์ ไม่มากกว่านั้น
    assert game.full_reads == 3, f"full grid reads: {game.full_reads}"


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
    print("test_solver.py OK")
