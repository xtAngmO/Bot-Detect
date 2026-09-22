"""เทสต์การจับคู่ช่อง ↔ เลขด้วยกติกาเกม (gridsolve) — รัน: .venv\\Scripts\\python.exe tests\\test_gridsolve.py"""
import itertools
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gridsolve

# ตารางจริงจากสกรีนช็อต scrcpy ของผู้ใช้ (เลขต่อไป = 6 → ตารางต้องมี 6..30 ครบ)
GRID = [
    [10, 12, 28, 26, 21],
    [14, 20, 9, 22, 25],
    [16, 30, 11, 6, 19],
    [24, 23, 13, 8, 29],
    [15, 17, 27, 18, 7],
]
TRUTH = {GRID[r][c]: (r, c) for r in range(5) for c in range(5)}
CELL_OF_15 = TRUTH[15]
CELL_OF_18 = TRUTH[18]


def _readings(overrides=None):
    readings = {(r, c): [GRID[r][c]] for r in range(5) for c in range(5)}
    readings.update(overrides or {})
    return readings


def test_hungarian_matches_brute_force() -> None:
    rng = random.Random(7)
    for n in range(1, 7):
        for _ in range(30):
            m = [[rng.randint(0, 20) for _ in range(n)] for _ in range(n)]
            picked = gridsolve.hungarian_max(m)
            assert sorted(picked) == list(range(n))
            best = max(sum(m[i][p[i]] for i in range(n)) for p in itertools.permutations(range(n)))
            assert sum(m[i][picked[i]] for i in range(n)) == best


def test_clean_readings_are_kept_as_is() -> None:
    sol = gridsolve.solve(_readings(), 6, 25, 50)
    assert sol.next == 6 and sol.where == TRUTH
    assert not sol.doubtful and not sol.conflicts


def test_confident_misread_is_flagged_then_fixed_by_votes() -> None:
    # วัดจริง (ภาพ scrcpy ย่อ 0.65 + JPEG 60): ช่อง 15 อ่านได้ 18 ชนกับช่อง 18 จริง
    first = _readings({CELL_OF_15: [18]})
    sol = gridsolve.solve(first, 6, 25, 50)
    assert {CELL_OF_15, CELL_OF_18} <= sol.conflicts, "ต้องขออ่านซ้ำทั้งสองช่องที่อ่านได้ 18"
    # อ่านซ้ำครบทุกรอบ OCR: ช่อง 15 ส่วนใหญ่อ่านถูก ช่อง 18 อ่านได้ 18 ตามเดิม
    votes = dict(first)
    votes[CELL_OF_15] = [18, 15, 15, 15, 18, 15]
    votes[CELL_OF_18] = [18, 18, 18, 18, 18, 18]
    sol = gridsolve.solve(votes, 6, 25, 50)
    assert sol.where == TRUTH and not sol.doubtful


def test_out_of_range_and_unreadable_cells_filled_by_elimination() -> None:
    # 35 อยู่นอกชุด 6..30 และ 8 อ่านไม่ออก — เลขที่ขาดคือ 25 กับ 8 ("35" ตรงกับ "25" หลักหน่วย)
    sol = gridsolve.solve(_readings({TRUTH[25]: [35], TRUTH[8]: [None]}), 6, 25, 50)
    assert sol.where == TRUTH
    assert sol.doubtful == {TRUTH[25], TRUTH[8]}


def test_duplicate_reading_is_ambiguous_until_reread() -> None:
    # ช่อง 25 อ่านได้ 29 ซ้ำกับช่อง 29 จริง — รอบเดียวแยกไม่ได้ว่าช่องไหนคือ 29 ตัวจริง ต้องขออ่านซ้ำทั้งคู่
    first = _readings({TRUTH[25]: [29]})
    sol = gridsolve.solve(first, 6, 25, 50)
    assert {TRUTH[25], TRUTH[29]} <= sol.conflicts
    votes = dict(first)
    votes[TRUTH[25]] = [29, 25, 25, 25, 25, 29]
    votes[TRUTH[29]] = [29] * 6
    sol = gridsolve.solve(votes, 6, 25, 50)
    assert sol.where == TRUTH and not sol.doubtful


def test_next_box_misread_is_overruled_by_grid() -> None:
    sol = gridsolve.solve(_readings(), 8, 25, 50)  # กรอบเลขต่อไปอ่าน 6 เป็น 8
    assert sol.next == 6 and sol.where == TRUTH
    sol = gridsolve.solve(_readings(), None, 25, 50)  # อ่านกรอบเลขต่อไปไม่ออกเลย
    assert sol.next == 6 and sol.where == TRUTH


def test_late_game_has_blank_cells() -> None:
    # เลขต่อไป 40: ตารางเหลือ 40..50 (11 ช่อง) ที่เหลือว่าง — ช่องว่างต้องไม่ได้เลขไป
    rng = random.Random(3)
    cells = [(r, c) for r in range(5) for c in range(5)]
    rng.shuffle(cells)
    truth = {n: cells[i] for i, n in enumerate(range(40, 51))}
    readings = {c: [None] for c in cells}
    for n, c in truth.items():
        readings[c] = [n]
    readings[truth[47]] = [41]  # อ่านผิดชนกับ 41 จริง
    sol = gridsolve.solve(readings, 40, 25, 50)
    assert sol.next == 40 and set(sol.where) == set(range(40, 51))
    assert sol.where[41] in (truth[41], truth[47])
    assert {truth[41], truth[47]} <= sol.conflicts


if __name__ == "__main__":
    test_hungarian_matches_brute_force()
    test_clean_readings_are_kept_as_is()
    test_confident_misread_is_flagged_then_fixed_by_votes()
    test_out_of_range_and_unreadable_cells_filled_by_elimination()
    test_duplicate_reading_is_ambiguous_until_reread()
    test_next_box_misread_is_overruled_by_grid()
    test_late_game_has_blank_cells()
    print("test_gridsolve.py OK")
