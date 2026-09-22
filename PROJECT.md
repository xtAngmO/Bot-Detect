# PROJECT.md — Number Sequence Bot (บอทเรียงเลข)

Single source of truth. อ่านไฟล์นี้ก่อนแก้อะไร.

## คืออะไร

บอทเดสก์ท็อป Windows (PySide6) ที่แก้เกม **"ตารางเลข" (Schulte grid)** อัตโนมัติ — เกมมีตัวเลข
1–25 สลับตำแหน่งในตาราง 5×5 ต้องแตะเรียงจากน้อยไปมาก เกมรันอยู่ใน **LDPlayer** (Android emulator
บน PC) เหมือนวิธีที่โปรเจกต์พี่น้อง `D:\Github\bot_detect_word` ใช้กับฟีเจอร์ "จับคู่การ์ด"

Flow: อ่านค่า **"เลขต่อไป"** ด้วย OCR → capture ตารางทั้งก้อน หั่นเป็น 25 ช่อง OCR หาตำแหน่งเลขนั้น
→ วาดวงไฮไลต์เขียวชี้เป้า → คลิกเมาส์อัตโนมัติ (ctypes) → วนซ้ำจนครบ `max_number` เลข

ต้นทางของงาน: ผู้ใช้ส่งสกรีนช็อตเกม (Thai UI, สนาม "เวลาที่ใช้"/"เลขต่อไป") แล้วขอให้สร้างบอทมา
เขียนไว้ใน `workspace/admin/Hiu` นี้ — ผู้ใช้ขอให้ "ทำเร็วๆ พร้อมรัน" จึงข้ามขั้น mockup UI (ดู
`plan/_TEMPLATE.html` ที่ยังเหลือไว้เผื่อทำเอกสารแผนอื่นในอนาคต — 3 mockup ตัวเลือก UI ที่เคยสร้าง
ถูกลบไปแล้วเพราะไม่ได้ใช้)

## Stack

- GUI: **PySide6** (Qt) — ธีมมืดง่ายๆ ฝัง QSS ตรงใน `app.py` (ยังไม่แยกเป็นระบบ theme เต็มแบบ
  `bot_detect_word`)
- Capture: **mss** (สร้าง instance ใหม่ทุก `grab()` — thread-safe)
- OCR: **pytesseract** → Tesseract ที่ `C:\Program Files\Tesseract-OCR\tesseract.exe` (auto-detect
  ใน `capture.configure_tesseract`, override ได้ผ่าน `Settings.tesseract_cmd`)
- คลิกเมาส์: `ctypes.SendInput` ตรงๆ (ไม่มี dependency เพิ่ม) — `mouse.py`
- Panic key: ไลบรารี `keyboard` (global hotkey, default `esc`) — ต้องรัน PowerShell แบบ
  Administrator บางเครื่องถึงจะดักคีย์ข้ามหน้าต่างได้ (เหมือน `bot_detect_word`)

## เทคนิคสำคัญที่ต้องรู้ก่อนแก้

### Overlay คลิกทะลุกลางกรอบ (`overlay.py`)
ใช้ `setMask(บริเวณทั้งหมด − รูตรงกลาง)` **ห้ามใช้ `Qt.WindowTransparentForInput`** — ทำให้คลิก
ทะลุทั้งบานจนลากขอบ/ย่อขยายไม่ได้เลย (บทเรียนที่บันทึกไว้ใน `bot_detect_word/PROJECT.md` แล้ว —
ยึดตามนั้น). ผลคือเฉพาะเส้นขอบหนา (`_BORDER = 6px`) รับคลิกได้ (ลาก/ย่อขยาย) ส่วนตรงกลางคลิกทะลุ
ไปโดนหน้าต่าง LDPlayer ข้างล่างแทน.

`FrameOverlay` มี callback `on_change(rect)` เรียกทุกครั้งที่ขยับ/ย่อขยาย/ปล่อยเมาส์ — `app.py`
ใช้มันอัปเดต `settings.grid_box` / `settings.next_box` แบบ live ไม่ต้องกดปุ่ม "บันทึกตำแหน่ง" แยก.

### พิกัด logical vs physical (`screenmap.py`) — สำคัญมาก
Qt 6 ใช้ **logical px** (กรอบ overlay, `config.json` เก็บค่านี้) แต่ **mss และ `SendInput` ใช้ physical
px** บนจอที่ scale ≠ 100% (เครื่องผู้ใช้: 2560×1600 @ 125%) ถ้าส่งพิกัด Qt ไปจับภาพตรงๆ จะจับผิดที่ทั้ง
ก้อน — เคยพังแล้ว: บอทขึ้น "อ่านเลขต่อไปไม่ออก" รัวๆ เพราะไปจับเมนูของหน้าต่างอื่น. `Solver.start()`
(GUI thread) สร้าง `ScreenMap.for_rect()` จากจอที่กรอบอยู่ แล้วลูปใช้ `to_physical()` ก่อน
`capture.grab`/`read_grid_numbers` ทุกครั้ง; ผลจาก OCR เป็น physical → คลิกตรงๆ ได้ ส่วนวงไฮไลต์
(หน้าต่าง Qt) แปลงกลับด้วย `point_to_logical()`. **ห้ามส่งพิกัดจาก settings เข้า capture/mouse ตรงๆ**

### OCR เลข (`capture.py`)
Pipeline ต่อภาพ: autocontrast → **`_crop_to_digits`** (connected components ของพิกเซลหมึก ≤150, ทิ้ง
ชิ้นที่แตะขอบภาพ = เส้นขอบ overlay ที่ mss จับติดมา/ขอบการ์ด/เศษเซลล์ข้างๆ, เก็บเฉพาะชิ้นที่สูง ≥60%
ของชิ้นสูงสุดในบรรทัดเดียวกัน = ทิ้งป้ายไทย "เลขต่อไป", เผื่อขอบ 30% ของความสูง) → **ปรับความสูงตัวเลข
ให้คงที่** → threshold → `MedianFilter(3)` → เติมขอบขาว 20px

**ห้ามกลับไปอัปสเกลตายตัว (เดิม 4x)** — ฟอนต์หนาของเกมจริงจะสูง ~150px จน Tesseract อ่าน "8" ไม่ออก
และอ่านผิดแบบมั่นใจ (25→29, 27→2). วัดกับ 576 ภาพ (เกมจริง + Arial/Arial Black/ส้ม 22–56px) และ
Arial Black 22–48px × เลข 1–50 (1,350 ภาพ): pipeline ใหม่ถูกหมด 0 ผิด, ของเดิมผิด 10/176

**`read_number_robust(img, valid_max)`** ลองตามลำดับ: `psm 6` @ 40px → 32px → 52px → `psm 7` @ 40px
→ `psm 8` @ 40px; ยอมรับค่าแรกที่อยู่ใน `1..valid_max`; ไม่มีเลย → คืนค่าแรกที่ไม่ใช่ None.
เหตุผล: `psm 8` อ่าน **`"1"` → `"4"`, `"11"` → `"411"`** แบบมั่นใจผิด (อันตราย — ตำแหน่งเลข 1 ทับเลข
4 จนคลิกผิด) จึงอยู่ท้ายสุด; `psm 6` พลาดแบบ None (ปลอดภัย) แต่อ่าน "8" ตัวเดียวฟอนต์หนาไม่ออกทุกขนาด
→ `psm 7` รับช่วง; Tesseract สะดุดบางขนาดแบบสุ่ม → ลองหลายความสูง. **แก้ลำดับนี้ต้องรัน
`tests/test_ocr.py` + `test_real_capture.py` + sweep หลายขนาดฟอนต์ก่อนเสมอ** — ค่าที่ดูดีกับภาพเดียว
มักพังที่ขนาดอื่น (เจอมาแล้วระหว่างจูน)

`cell_pad_ratio` default **0.16** — inset แต่ละเซลล์ 16% ต่อด้านก่อนตัดภาพ กันขอบข้างเซลล์เพื่อน
บ้านหลุดเข้ามาปน (ยิ่งตารางไม่มีช่องว่างชัดระหว่างการ์ด ยิ่งต้องการ pad สูง).

### Solver loop (`solver.py`)
รันบน `threading.Thread` แยก ไม่ใช่ QThread — สื่อสารกลับ UI ผ่าน **Qt Signal** (`log`,
`target_found`, `progress`, `finished`) ซึ่ง Qt จะคิวข้าม thread ให้เองอัตโนมัติ (ปลอดภัย ไม่ต้อง
`QMetaObject.invokeMethod` เอง). Safety: หยุดเองถ้าหาเลขเป้าหมายไม่เจอในตารางติดกันเกิน
`settings.max_consecutive_miss` (default 20) รอบ — กันวนเปล่าๆ ไม่จบตอน OCR อ่านพังต่อเนื่อง.

**ความเร็ว (เป้าผู้ใช้: 50 เลขใน 20 วินาที)** — OCR หนึ่งครั้ง ~77ms (เกือบทั้งหมดคือค่าเปิด process
tesseract) และ grab หนึ่งครั้ง ~17ms (1 เฟรม vsync) คือต้นทุนหลักทั้งหมด. แบบเดิมอ่าน 25 ช่องใหม่ทุกคลิก
+ นอนตายตัว 350ms = ~2.5s/คลิก. ตอนนี้:
- **cache เลขทุกช่อง** — เกมไม่สลับตำแหน่ง กดเลข n แล้วช่องนั้นกลายเป็น n+25 ที่เดิม (ยืนยันจากสกรีนช็อต
  2 ภาพ) ช่องที่กดแล้วเข้า `stale` และอ่านใหม่เฉพาะตอนหาเลขใน cache ไม่เจอ (ปกติรอบเดียวตอนเลข 26)
- **ยืนยันคลิกด้วยกรอบเลขต่อไป** (`_wait_for_advance`) — grab ถี่ๆ แต่ OCR เฉพาะตอนภาพเปลี่ยน ต้องได้
  target+1 ถึงนับ; ไม่ขยับใน 1.5s → ล้าง cache อ่านทั้งตารางใหม่ (self-healing)
- OCR ขนานใน `capture._ocr_pool` (12 worker, `OMP_THREAD_LIMIT=1`): อ่านทั้งตาราง 1.9s → 0.3s และ
  กรอบเลขต่อไปใช้ `read_number_robust(parallel=True)` ยิงทุกรอบ fallback พร้อมกัน
- วัดด้วย `tests/test_solver.py` + ต้นทุนจริง: **50 เลข ≈ 8 วินาที (159ms/คลิก)** ยังไม่รวมเวลาเกมตอบสนอง
- ถ้าเกมเวอร์ชันอื่นสลับตำแหน่งหลังกด ระบบยังถูก (คลิกไม่ติด → resync) แต่จะช้าลงมาก
- **"เวลาเป้าหมาย (วินาที)"** (`target_total_s`, 0 = เร็วสุด) — ผู้ใช้อยากให้จบ ~18s ไม่ใช่เร็วสุด
  คลิกที่ k นัดไว้ที่ คลิกแรก + k × T/(max_number−1) (นับจากนัด ไม่ใช่นอนเท่ากันทุกคลิก จึงไม่เพี้ยนตาม
  ความเร็ว OCR/เกม) — `click_delay_ms` ตั้งแบบนี้แทนไม่ได้เพราะเวลาตอบสนองของเกมไม่แน่นอน

## โครงสร้างโค้ด

ดูตาราง "โครงสร้างโค้ด" ใน `README.md` — ไม่ซ้ำไว้ที่นี่สองที่.

## รันและทดสอบ

```powershell
.venv\Scripts\python.exe main.py                              # รันแอป
.venv\Scripts\python.exe tests\test_ocr.py                    # OCR เลขเดี่ยว
.venv\Scripts\python.exe tests\test_grid.py                   # OCR ตาราง 5x5 เต็ม (สุ่มทุกรัน)
.venv\Scripts\python.exe tests\test_real_capture.py           # ภาพเกมจริงจาก tests/fixtures/ (จอ 125%)
.venv\Scripts\python.exe tests\test_solver.py                 # ลูป solver กับเกมจำลอง (ลำดับ + อ่านตารางครั้งเดียว)
.venv\Scripts\python.exe tests\test_screenmap.py              # แปลงพิกัด logical <-> physical
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe tests\test_app_smoke.py  # สร้างหน้าต่าง headless
```

ทั้ง 6 เทสต์เขียวหมดก่อนแก้อะไรเสร็จเสมอ (ดู `test_app_smoke.py` ที่ no-op `Settings.save`
ป้องกัน `config.json` จริงโดนทับ — อย่าลบบรรทัดนั้น).

## ยังไม่ได้ทำ / ข้อจำกัดที่รู้อยู่

- เกมจริงที่ผู้ใช้เล่นตอนนี้อยู่ใน **Chrome (shopee arcade)** ไม่ใช่ LDPlayer — มีภาพจริงชุดเดียวใน
  `tests/fixtures/` (ตัวเลข 1–50 บนตาราง 5×5, `max_number` = 50) ถ้าเกมเปลี่ยนสี/พื้นเข้ม ต้องปรับ
  `_INK_THRESHOLD`
- `mouse._abs_coords` ใช้ขนาดจอหลักเท่านั้น — กรอบบนจอที่สองจะคลิกผิด (ยังไม่รองรับ virtual desktop)
- ยังไม่มี build เป็น `.exe` portable (ผู้ใช้ขอ "เร็วที่สุด" จึงข้ามไปก่อน รันจาก `.venv` เท่านั้น)
- ยังไม่มี auto-detect ตำแหน่งหน้าต่าง LDPlayer (ผู้ใช้ลากกรอบเองด้วยมือทุกครั้งที่เกมขยับ)
- ไม่มีระบบ export/import ค่า config ข้ามเครื่อง (ต่างจาก `bot_detect_word` ที่มีปุ่ม Export)

## ประวัติการแก้ไข

- **2026-09-22** — สร้างโปรเจกต์ครั้งแรก: overlay 2 กรอบ (ตาราง/เลขต่อไป) + OCR 2-pass (psm 6→8
  + valid_max guard) + solver loop + ctypes click + panic key + เทสต์ headless 3 ตัว
- **2026-09-22** — แก้ "อ่านเลขต่อไปไม่ออก" กับเกมจริง: (1) แปลงพิกัด logical→physical (`screenmap.py`)
  เพราะจอ 125% ทำให้จับภาพผิดที่ (2) OCR ตัดเหลือตัวเลข + ปรับความสูงคงที่ + ลำดับ psm 6→7→8 หลายขนาด
  (3) Ctrl+C ในเทอร์มินัลปิดแอปปกติ (เดิม KeyboardInterrupt traceback ใน `_tick_elapsed`) — `main.py`
  (4) เพิ่ม `tests/test_real_capture.py` (+fixtures) และ `tests/test_screenmap.py`
- **2026-09-22** — เร่งความเร็ว ~2.5s → ~0.16s ต่อคลิก: cache ตำแหน่งเลข + ยืนยันคลิกจากกรอบเลขต่อไป
  แทนการนอนรอ, OCR ขนาน, ลบ `cooldown_after_click_ms` (350ms ที่ซ่อนอยู่ ไม่มีใน UI), mouse settle
  30→10ms + `tests/test_solver.py`
