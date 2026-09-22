"""จับคู่ช่อง ↔ เลข ด้วยกติกาของเกม แทนการเชื่อ OCR ทีละช่อง

กติกา: ตารางมีเลข next .. next + rows×cols − 1 (ไม่เกิน max) ครบทุกตัว ตัวละช่อง ที่เหลือว่าง — เพราะกด n
แล้วช่องเดิมกลายเป็น n + rows×cols. OCR จึงแค่ต้อง "แยก" เลขในชุดที่รู้อยู่แล้ว: ให้คะแนนทุกคู่ (ช่อง, เลข)
จากผล OCR ทุกรอบของช่องนั้น แล้วเลือกการจับคู่ที่คะแนนรวมสูงสุด (Hungarian). อ่านผิดแบบมั่นใจ (วัดจริงกับ
ภาพ scrcpy ย่อ + JPEG: 15 → 18) จะชนกับช่องที่เป็น 18 จริง ส่วนเลขที่ขาด/อ่านไม่ออกถูกเติมจากการตัดตัวเลือก
— ช่องที่ได้เลขมาแบบไม่มีผล OCR ตรงรองรับอยู่ใน `doubtful` ให้ผู้เรียกอ่านซ้ำหลายรอบแล้วแก้ใหม่

pure Python ล้วน (ไม่มี numpy) — ตาราง 25×25 แก้ได้ในไม่กี่ ms
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

Cell = Tuple[int, int]

_EXACT = 10  # ต่อหนึ่งรอบ OCR ที่อ่านได้ตรงเลขนี้
_DIGIT = 1  # ต่อหลักที่ตรงตำแหน่ง (ความยาวเท่ากัน) — แค่ใช้ตัดสินตอนไม่มีรอบไหนอ่านตรง
_BLANK = 4  # ต่อหนึ่งรอบที่อ่านไม่ออก ถ้าจับคู่กับ "ช่องว่าง"


@dataclass
class Solution:
    next: int  # เลขต่อไปที่สอดคล้องกับตารางที่สุด
    where: Dict[int, Cell]  # เลข → ช่อง
    doubtful: Set[Cell] = field(default_factory=set)  # ช่องที่เลขที่ได้ไม่มีผล OCR ตรงรองรับเป็นเสียงข้างมาก
    conflicts: Set[Cell] = field(default_factory=set)  # doubtful + ช่องที่อ่านได้เลขเดียวกับมัน — ควรอ่านซ้ำ
    score: int = 0


def score(readings: Sequence[Optional[int]], n: Optional[int]) -> int:
    """คะแนนที่ช่องนี้จะเป็นเลข n (None = ช่องว่าง) จากผล OCR ทุกรอบของช่อง."""
    total = 0
    for r in readings:
        if n is None:
            total += _BLANK if r is None else 0
        elif r == n:
            total += _EXACT
        elif r is not None and len(str(r)) == len(str(n)):
            total += _DIGIT * sum(a == b for a, b in zip(str(r), str(n)))
    return total


def solve(
    readings: Dict[Cell, List[Optional[int]]], next_hint: Optional[int], n_cells: int, max_number: int
) -> Optional[Solution]:
    """เลือกเลขต่อไป + การจับคู่ที่คะแนนรวมสูงสุด ลองทั้งเลขจากกรอบเลขต่อไป (next_hint) และเลขน้อยสุดที่อ่าน
    ได้จากตาราง — ตารางต้องมี next เสมอ กรอบเลขต่อไปอ่านผิดจึงถูกตารางแก้ได้ (เสมอกันเชื่อ next_hint)."""
    candidates: List[int] = []
    if next_hint is not None and 1 <= next_hint <= max_number:
        candidates.append(next_hint)
    seen = [r for rs in readings.values() for r in rs if r is not None and 1 <= r <= max_number]
    if seen and min(seen) not in candidates:
        candidates.append(min(seen))
    best: Optional[Solution] = None
    for nxt in candidates:
        sol = _assign(readings, nxt, n_cells, max_number)
        if best is None or sol.score > best.score:
            best = sol
    return best


def _assign(readings: Dict[Cell, List[Optional[int]]], nxt: int, n_cells: int, max_number: int) -> Solution:
    numbers: List[Optional[int]] = list(range(nxt, min(nxt + n_cells - 1, max_number) + 1))
    cells = sorted(readings)
    cols = numbers + [None] * max(0, len(cells) - len(numbers))  # ช่องว่าง (เลขเกิน max)
    size = max(len(cells), len(cols))
    rows: List[Optional[Cell]] = list(cells) + [None] * (size - len(cells))  # แถวหลอก ถ้าช่องน้อยกว่าเลข
    cols += [None] * (size - len(cols))
    matrix = [[score(readings[c], n) if c is not None else 0 for n in cols] for c in rows]
    picked = hungarian_max(matrix)

    where: Dict[int, Cell] = {}
    doubtful: Set[Cell] = set()
    total = 0
    for i, j in enumerate(picked):
        cell, n = rows[i], cols[j]
        total += matrix[i][j]
        if cell is None:
            continue
        if n is not None:
            where[n] = cell
        votes = readings[cell]
        agree = sum(r == n for r in votes)
        if agree == 0 or any(votes.count(r) > agree for r in votes):
            doubtful.add(cell)
    suspect = {r for c in doubtful for r in readings[c] if r is not None}
    conflicts = doubtful | {c for c in cells if suspect & set(readings[c])}
    return Solution(nxt, where, doubtful, conflicts, total)


def hungarian_max(matrix: List[List[int]]) -> List[int]:
    """การจับคู่แถว → คอลัมน์ ที่ผลรวมสูงสุด ของเมทริกซ์จัตุรัส (Kuhn–Munkres O(n³), potentials)."""
    n = len(matrix)
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)  # p[j] = แถว (1-based) ที่ได้คอลัมน์ j
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = -matrix[i0 - 1][j - 1] - u[i0] - v[j]  # ติดลบ = หา min cost
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    picked = [0] * n
    for j in range(1, n + 1):
        picked[p[j] - 1] = j - 1
    return picked
