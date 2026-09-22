# Number Sequence Bot

A Windows desktop bot that plays **Schulte-grid number games** by itself. These games show the numbers
1–25 shuffled on a 5×5 grid and you tap them in ascending order. When you tap `n`, its cell shows
`n + 25`, so a full game runs from 1 to 50. The bot reads the grid from the screen with OCR, works out
where each number is, and taps them in order at the speed you set.

The game can be on an Android phone mirrored with [scrcpy](https://github.com/Genymobile/scrcpy), in an
emulator such as LDPlayer, or in a browser.

## Features

- **Two modes**
  - **OCR, 2 frames**: watches the grid and the game's "next number" display. After every tap it checks
    that the game moved on, and if a tap is dropped it re-reads the grid and recovers.
  - **Grid only**: reads the grid once, then taps the whole sequence without waiting for the game. This
    is fastest, but it cannot tell when a tap was missed.
- **Reliable taps on a real phone.** On a scrcpy window the bot does not click with the mouse. It
  starts a second, control-only scrcpy server on the phone and sends touch events at exact phone
  coordinates. Your mouse stays free and your own scrcpy session keeps working.
- **Rule-checked OCR.** The grid always holds exactly the numbers `next … next + 24`. The bot matches
  cells to that known set with the Hungarian algorithm and re-reads any cell that conflicts, so a
  confident misread (for example 15 read as 18) is fixed before it can cause a wrong tap.
- **Target time.** For example, 50 numbers in 8 seconds. Taps are pipelined: up to 3 can be in flight
  before the display confirms them.
- **Instant start.** While idle, the bot connects to the phone and pre-reads the grid. If the grid has
  not changed when you press Start, the first tap happens immediately.
- **Clear status.** A large status line shows idle, starting, running (pulsing dot, current number,
  elapsed time), done, stopped, or error with the reason. **Esc** stops the bot from any window.
- Dark UI with Anuphan (Thai) and JetBrains Mono fonts and Lucide icons.

## Requirements

- Windows 10 or 11
- Python 3.11+ (developed on 3.14)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed at
  `C:\Program Files\Tesseract-OCR\tesseract.exe`. It is detected automatically. For another location,
  set `tesseract_cmd` in `config.json`.
- For playing on a phone: **scrcpy 4.x** (the official Windows zip or `winget install Genymobile.scrcpy`,
  which ship `adb.exe` and `scrcpy-server` next to `scrcpy.exe`), with USB debugging enabled on the phone

## Install

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Run

```powershell
.venv\Scripts\python.exe main.py
```

## Usage

1. Open the game so the grid is visible on screen. If it runs on a phone, start `scrcpy` first. Keep
   the game window uncovered, because the bot reads the numbers from the screen.
2. Pick a **mode** in the *Mode* section.
3. In the *Screen frames* section, press **Show grid frame** and drag the green frame over the whole
   5×5 grid. Drag the frame's edge to move it, and drag the bottom-right handle to resize it.
4. *OCR mode only:* press **Show next-number frame** and drag the blue frame over the number in the
   game's "next number" card.
5. Adjust *Grid and pacing* if needed:

   | Setting | Meaning |
   | --- | --- |
   | Rows × columns | Grid size (default 5 × 5) |
   | Max number | Last number to tap (default 50) |
   | Target time (s) | Time from the first tap to the last; `0` = as fast as possible |
   | Delay after tap (ms) | Extra pause after each tap |
   | Retry interval (ms) | Wait before re-reading when something could not be read |

6. Press **Start**. The same button becomes **Stop** while the bot runs, and **Esc** also stops it.

The frame positions and settings are saved to `config.json` next to the script.

> The UI labels are in Thai. The section names above are translations of the on-screen labels.

## How it works

1. **Capture.** `mss` grabs the frames from the screen. Qt works in logical pixels, but capture and
   input use physical pixels, so `screenmap.py` converts between them for displays scaled above 100%.
2. **OCR.** Each cell is cropped to its digits and scaled so the digits are about 40 px tall. Tesseract
   then reads it in digits-only mode, trying page-segmentation modes 6, 7 and 8 at a few sizes.
3. **Rule check.** `gridsolve.py` matches every cell to the set of numbers the grid must contain and
   picks the best overall assignment. Cells that disagree are re-read with every OCR mode. The
   next-number display is checked against the grid the same way.
4. **Prediction.** Tapping `n` turns its cell into `n + 25`, so the grid only needs to be read once per
   game.
5. **Tapping and confirmation.** In OCR mode a watcher thread reads the next-number display while taps
   continue. If the oldest unconfirmed tap is still unconfirmed after 1.5 s, the bot re-reads the whole
   screen and continues from the game's real state.
6. **Input path.** How the bot taps depends on the window under the point:
   - **scrcpy window:** a touch is injected into the phone through a second, control-only scrcpy server
     (`phonetap.py`). The bot always uses the `adb.exe` and `scrcpy-server` from the folder of the
     running scrcpy, because a different adb version would restart the adb server and cut off scrcpy.
     If the phone cannot be reached, it falls back to posting mouse messages to the window.
   - **Any other window:** the bot moves the mouse and clicks with `SendInput`.

## Tests

```powershell
.venv\Scripts\python.exe tests\test_ocr.py           # single-number OCR
.venv\Scripts\python.exe tests\test_grid.py          # full 5x5 grid OCR (randomised)
.venv\Scripts\python.exe tests\test_real_capture.py  # real game captures (browser at 125%, scrcpy)
.venv\Scripts\python.exe tests\test_gridsolve.py     # rule-based cell/number matching
.venv\Scripts\python.exe tests\test_solver.py        # solver loop against a simulated game
.venv\Scripts\python.exe tests\test_screenmap.py     # logical/physical coordinates
.venv\Scripts\python.exe tests\test_mouse.py         # click routing (never moves the real mouse)
.venv\Scripts\python.exe tests\test_phonetap.py      # touch injection against a fake scrcpy server
$env:QT_QPA_PLATFORM = "offscreen"; .venv\Scripts\python.exe tests\test_app_smoke.py
```

None of the tests need a phone, a game or a visible screen. The UI test replaces `Settings.save`
with a no-op, so your real `config.json` is never overwritten.

## Project layout

| Path | Purpose |
| --- | --- |
| `main.py` | Entry point |
| `app.py` | Main window: status, start/stop, mode, frames, settings, log |
| `theme.py` / `widgets.py` | Design tokens, stylesheet, fonts, icons, and small widgets |
| `overlay.py` | Draggable, click-through frames and the target highlight |
| `capture.py` | Screen capture, digit OCR, grid comparison |
| `gridsolve.py` | Rule-based OCR correction (Hungarian assignment) |
| `solver.py` | Game loop, pacing, pipelined taps, idle pre-reading |
| `mouse.py` | Click routing: phone touch, window messages, or `SendInput` |
| `phonetap.py` | Second scrcpy server (control only) for touch injection |
| `screenmap.py` | Logical ↔ physical screen coordinates |
| `config.py` | Settings model and `config.json` load/save |
| `fonts/`, `assets/icons/` | Bundled fonts and icons (license files included) |
| `tests/` | Headless tests and real-capture fixtures |
| `phone_remote/` | A separate app for mirroring and controlling an Android phone (see its own README) |

## Known limitations

- Windows only.
- The game must stay visible on screen, because OCR reads the screen. When playing on a phone, taps
  still work if the scrcpy window is covered, but reading does not.
- Grid-only mode cannot detect a dropped tap. Every tap after it will land on the wrong number.
- Phone touch injection uses the scrcpy 4.x message format. A future major scrcpy version may need an
  update. Until then, the bot falls back to the less reliable window messages.
- The `SendInput` path only supports the primary monitor.
- OCR assumes dark digits on a light background. A different colour scheme needs changes to
  `_INK_THRESHOLD` in `capture.py`.
- There is no packaged `.exe` yet. Run it from source.

## Credits

- Fonts: **Anuphan** and **JetBrains Mono** (SIL Open Font License 1.1; license files are in `fonts/`)
- Icons: **[Lucide](https://lucide.dev)** (ISC; see `assets/icons/LICENSE`)
- Touch injection talks to the **scrcpy** server (Apache 2.0). The bot does not bundle it; it uses the
  copy that ships with your scrcpy install.
