# Number Sequence Bot

A **Windows and macOS** desktop bot that plays **Schulte-grid number games** by itself. These games show the numbers
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

- Windows 10/11, or macOS 12+ (Apple Silicon or Intel)
- Python 3.11+ (developed on 3.14 for Windows, 3.13 for macOS)
- **Tesseract OCR** — **already included in the packaged downloads**, nothing to install. Only needed
  when running from source: found automatically in `PATH` or at the standard install location
  ([Windows](https://github.com/UB-Mannheim/tesseract/wiki): `C:\Program Files\Tesseract-OCR\tesseract.exe`;
  macOS: `brew install tesseract`). For another location, set `tesseract_cmd` in `config.json`.
- For playing on a phone: **scrcpy 4.x** with USB debugging enabled
  - Windows: the official zip or `winget install Genymobile.scrcpy` — ships `adb.exe` and
    `scrcpy-server` next to `scrcpy.exe`
  - macOS: `brew install scrcpy` — `scrcpy-server` lives in `share/scrcpy/` and `adb` comes from
    `PATH`; both are located automatically

### macOS permissions

macOS blocks screen reading and key watching until you allow them. Grant these to whatever runs the
bot (Terminal, iTerm, or the packaged app) in **System Settings → Privacy & Security**:

| Permission | Needed for | If missing |
| --- | --- | --- |
| **Screen & System Audio Recording** | reading the grid | capture silently returns only the desktop wallpaper, so the bot cannot read any number — it warns you at startup |
| **Accessibility** | the **Esc** panic key working from any window | the bot still runs; stop it from the bot window instead |

## Install

```powershell
# Windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

```bash
# macOS
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```powershell
.venv\Scripts\python.exe main.py   # Windows
```

```bash
.venv/bin/python main.py            # macOS
```

## Build a release yourself

PyInstaller cannot cross-compile, so each file must be built on its own system. Tesseract must be
installed on the build machine first — the spec copies it into the result.

```powershell
# Windows  ->  dist\NumberSequenceBot.exe  (single file)
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller --noconfirm --clean NumberSequenceBot.spec
```

```bash
# macOS  ->  dist/NumberSequenceBot.app
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pyinstaller --noconfirm --clean NumberSequenceBot.spec
# zip it with ditto, not zip — the bundle contains symlinks
ditto -c -k --keepParent dist/NumberSequenceBot.app NumberSequenceBot-macos-arm64.zip
```

Pushing a `v*` tag runs the same two builds on GitHub Actions and attaches both to a release.

## Usage

1. Open the game so the grid is visible on screen. If it runs on a phone, start `scrcpy` first. Keep
   the game window uncovered, because the bot reads the numbers from the screen.
2. Pick a **mode** in the *Mode* section.
3. In the *Screen frames* section, press **Show grid frame** and drag the green frame over the whole
   5×5 grid. Drag the frame's edge to move it, and drag the bottom-right handle to resize it. The frame
   draws the cell lines, so line them up with the gaps between the cards.
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

1. **Capture.** `mss` grabs the frames from the screen. Qt works in logical pixels; `screenmap.py`
   converts those to whatever capture and input actually want. On Windows that means physical pixels,
   so it scales by the display's ratio for displays above 100%. On macOS both `mss` and `CGEvent`
   already use the same points as Qt, so no conversion is applied — scaling by the Retina ratio there
   would send every capture and click to twice the intended coordinates.
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
     (`phonetap.py`) — the same on both systems, and the main path. On Windows the bot uses the
     `adb.exe` and `scrcpy-server` from the folder of the running scrcpy, because a different adb
     version would restart the adb server and cut off scrcpy; on macOS `scrcpy-server` is read from
     `share/scrcpy/` and `adb` from `PATH`, which is the same one scrcpy itself uses.
   - **If the phone cannot be reached:** Windows falls back to posting mouse messages to the window.
     macOS has no equivalent — the system does not let one app post events into another's window — so
     it falls back to a real mouse click, which needs the scrcpy window in front.
   - **Any other window:** the bot moves the mouse and clicks (`SendInput` on Windows, `CGEvent` on
     macOS).

## Tests

Run the whole suite with pytest:

```powershell
.venv\Scripts\python.exe -m pytest tests\   # Windows
```

```bash
.venv/bin/python -m pytest tests/            # macOS
```

| Test | Covers |
| --- | --- |
| `test_ocr.py` | single-number OCR |
| `test_grid.py` | full 5×5 grid OCR (randomised) |
| `test_real_capture.py` | real game captures (browser at 125%, scrcpy) |
| `test_gridsolve.py` | rule-based cell/number matching |
| `test_solver.py` | solver loop against a simulated game |
| `test_screenmap.py` | logical ↔ device coordinates |
| `test_mouse.py` | Windows click routing (skipped on macOS) |
| `test_mouse_mac.py` | macOS click routing (skipped on Windows) |
| `test_phonetap.py` | touch injection against a fake scrcpy server |
| `test_app_smoke.py` | UI builds and starts headless |

The two click-routing tests are platform-specific and skip themselves on the other system, so the
suite is green on both. Neither moves the real mouse. No test needs a phone, a game or a visible
screen, and the UI test replaces `Settings.save` with a no-op so your real `config.json` is never
overwritten.

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
| `mouse.py` | Picks the click backend for the current system |
| `mouse_win.py` | Windows clicks: phone touch, window messages, or `SendInput` |
| `mouse_mac.py` | macOS clicks: phone touch or `CGEvent` |
| `phonetap.py` | Second scrcpy server (control only) for touch injection |
| `hotkey.py` | Panic key: `keyboard` on Windows, a Quartz event tap on macOS |
| `screenmap.py` | Qt ↔ capture/click coordinates (Windows scaling, macOS points) |
| `config.py` | Settings model and `config.json` load/save |
| `fonts/`, `assets/icons/` | Bundled fonts and icons (license files included) |
| `tests/` | Headless tests and real-capture fixtures |

## Known limitations

- The game must stay visible on screen, because OCR reads the screen. When playing on a phone, taps
  still work if the scrcpy window is covered, but reading does not.
- Grid-only mode cannot detect a dropped tap. Every tap after it will land on the wrong number.
- Phone touch injection uses the scrcpy 4.x message format. A future major scrcpy version may need an
  update. Until then, the bot falls back to the less reliable paths described above.
- The `SendInput` path (Windows) only supports the primary monitor.
- On macOS, leave the scrcpy window at the size scrcpy gives it. If you stretch it taller than the
  phone's aspect ratio, the black bars that appear cannot be told apart from the window's title bar,
  and taps drift down by the height of the bar.
- OCR assumes dark digits on a light background. A different colour scheme needs changes to
  `_INK_THRESHOLD` in `capture.py`.
- The packaged builds carry their own copy of Tesseract, but **not** scrcpy or adb — install those
  yourself to play on a phone.
- The macOS build is Apple Silicon (arm64) only; it does not run on Intel Macs. The two downloads are
  not interchangeable — `.exe` is Windows only and `.app` is macOS only.
- The packaged builds are unsigned. Windows SmartScreen shows "More info → Run anyway"; on macOS use
  right-click → Open the first time, or run `xattr -dr com.apple.quarantine "Number Sequence Bot.app"`.

## Credits

- Fonts: **Anuphan** and **JetBrains Mono** (SIL Open Font License 1.1; license files are in `fonts/`)
- Icons: **[Lucide](https://lucide.dev)** (ISC; see `assets/icons/LICENSE`)
- Touch injection talks to the **scrcpy** server (Apache 2.0). The bot does not bundle it; it uses the
  copy that ships with your scrcpy install.
