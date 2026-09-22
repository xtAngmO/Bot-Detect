"""Design tokens + QSS + ฟอนต์ + ไอคอน — หน้าตาเดียวกับโปรเจกต์พี่น้อง bot_detect_word (Word Detect Bot)

ค่าสี/ขนาด/QSS ยกมาจาก `D:\\Github\\bot_detect_word\\ui_theme.py` (ธีมมืด) ตัดเหลือเฉพาะส่วนที่บอทนี้ใช้
ห้ามมีสี hex ลอยในไฟล์อื่น ให้ดึงจาก `PALETTE` เท่านั้น
- ฟอนต์ฝังมาในตัว: Anuphan (ไทย) + JetBrains Mono (ตัวเลข) ใน `fonts/` (OFL)
- ไอคอน Lucide (ISC) ใน `assets/icons/` — ย้อมสีก่อน render เพราะ QSvgRenderer ไม่รู้จัก currentColor
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

import apppaths

BASE_DIR = apppaths.resource_dir()  # แพ็กแล้วไฟล์ประกอบอยู่ในโฟลเดอร์ที่ PyInstaller แตกไว้
FONT_DIR = os.path.join(BASE_DIR, "fonts")
ICON_DIR = os.path.join(BASE_DIR, "assets", "icons")

PALETTE: dict[str, str] = {
    "bg": "#0a0a0a",          # พื้นหน้าต่าง
    "panel": "#0d0d0e",       # topbar
    "sunken": "#070708",      # พื้นกล่อง log
    "elev": "#161618",        # ช่องกรอก ปุ่มรอง
    "elev-hi": "#1f1f22",     # hover
    "press": "#0e0e10",
    "hair": "#1a1a1c",        # เส้นคั่นในเซ็กชัน
    "border": "#262628",      # เส้นคั่นระหว่างเซ็กชัน
    "border-hi": "#3a3a3d",
    "text": "#ededed",
    "text-dim": "#a0a0a0",
    "text-faint": "#808080",
    "white": "#fafafa",
    "white-hi": "#ffffff",
    "white-press": "#d4d4d4",
    "on-white": "#0a0a0a",
    "green": "#22c55e",       # กำลังทำงาน / สำเร็จ
    "amber": "#f59e0b",       # กำลังเริ่ม / คำเตือน
    "log-act": "#7fb2f7",
    "log-err": "#f87171",
    "sel": "#3a3a3d",
}

# type scale / geometry (px) — ตรงกับ bot_detect_word
T_MICRO = 11
T_LOG = 12
T_BODY = 14
T_TITLE = 18
T_LEAD = 23
T_DISPLAY = 29
RADIUS = 4
H_CTRL = 28
H_RUN = 36

# ฟอนต์สำรอง — ตัวแรกคือที่ฝังมากับโปรแกรม (fonts/) จึงได้ตัวนั้นเสมออยู่แล้ว ที่เหลือเผื่อโหลดไม่ขึ้น
# ใส่เฉพาะที่มีจริงในระบบนั้น: ถ้าใส่ชื่อฟอนต์ที่ไม่มี Qt จะไล่สแกนฟอนต์ทั้งเครื่องแล้วเตือน
# "Populating font family aliases took ... Replace uses of missing font family" ทุกครั้งที่เปิดโปรแกรม
if sys.platform == "darwin":
    # ไม่ใส่ SF Pro / SF Mono — เป็นฟอนต์ระบบที่ Qt มองไม่เห็นเป็น family ธรรมดา (ตรวจแล้วขึ้น missing)
    FONT_SANS = ["Anuphan", "Helvetica Neue"]
    FONT_MONO = ["JetBrains Mono", "Menlo", "Monaco", "Courier New"]
else:
    FONT_SANS = ["Anuphan", "Segoe UI"]
    FONT_MONO = ["JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New"]
# SemiBold ของ JetBrains ต้องขอเป็น family แยก — ตั้ง weight บน family ปกติแล้ว Qt สังเคราะห์ตัวหนาให้เอง (เยิน)
FONT_MONO_BOLD = ["JetBrains Mono SemiBold"] + FONT_MONO


def SP(n: int) -> int:
    """ระยะห่างบนกริด 4px."""
    return int(n) * 4


_fonts_loaded = False


def load_fonts() -> None:
    global _fonts_loaded
    if _fonts_loaded:
        return
    if os.path.isdir(FONT_DIR):
        for fn in sorted(os.listdir(FONT_DIR)):
            if fn.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(FONT_DIR, fn))
    _fonts_loaded = True


def sans_font(size: int = T_BODY, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(FONT_SANS)
    f.setPixelSize(int(size))
    f.setWeight(weight)
    return f


def mono_font(size: int = T_MICRO, bold: bool = False, mix: bool = False) -> QFont:
    """ตัวเลข/ละติน — `mix=True` เมื่อสตริงมีไทยปน (ต่อท้าย Anuphan ไม่งั้น baseline ไทยหลุด)."""
    f = QFont()
    base = FONT_MONO_BOLD if bold else FONT_MONO
    f.setFamilies(base + FONT_SANS if mix else base)
    f.setPixelSize(int(size))
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


# ---------------------------------------------------------------- icons
_RE_STROKE_W = re.compile(r'stroke-width="[^"]*"')
_pix_cache: dict[tuple, QPixmap] = {}
_path_cache: dict[tuple, str] = {}


def _tinted_svg(name: str, color: str, stroke: float = 1.5) -> bytes:
    with open(os.path.join(ICON_DIR, f"{name}.svg"), "r", encoding="utf-8") as fh:
        src = fh.read()
    src = src.replace("currentColor", color)
    return _RE_STROKE_W.sub(f'stroke-width="{stroke}"', src).encode("utf-8")


def pixmap(name: str, color: str, size: int = 16, stroke: float = 1.5) -> QPixmap:
    key = (name, color, size, stroke)
    if key not in _pix_cache:
        from PySide6.QtGui import QGuiApplication

        dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        renderer = QSvgRenderer(QByteArray(_tinted_svg(name, color, stroke)))
        painter = QPainter(pm)
        renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
        painter.end()
        pm.setDevicePixelRatio(dpr)
        _pix_cache[key] = pm
    return _pix_cache[key]


def icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    return QIcon(pixmap(name, color or PALETTE["text"], size))


def tinted_svg_path(name: str, color: str, size: int = 16) -> str:
    """ไฟล์ svg ย้อมสีแล้วใน temp — ให้ QSS อ้าง `url(...)` ได้ (QSS ย้อมสีไอคอนเองไม่ได้)."""
    key = (name, color, size)
    if key not in _path_cache:
        folder = os.path.join(tempfile.gettempdir(), "number_bot_icons")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{name}-{color.strip('#')}-{size}.svg")
        with open(path, "wb") as fh:
            fh.write(_tinted_svg(name, color))
        _path_cache[key] = path.replace("\\", "/")
    return _path_cache[key]


# ---------------------------------------------------------------- QSS
_QSS = """
* { outline: 0; }
/* ห้ามประกาศ font-* ในกฎ QWidget กว้างๆ — QSS ชนะ setFont() เสมอ ตัวเลขใหญ่/mono ที่ตั้งใน Python จะถูกดึง
   กลับเป็น 14px หมด (บทเรียนจาก bot_detect_word) ฟอนต์ฐานมาจาก QApplication.setFont() ใน apply() */
QWidget { background: transparent; color: %(text)s; }
QMainWindow, QDialog { background: %(bg)s; }
QWidget#appRoot { background: %(bg)s; }
QWidget#topbar { background: %(panel)s; border-bottom: 1px solid %(border)s; }
QLabel#appName { font-size: %(t_title)spx; font-weight: 600; color: %(white)s; }
QToolTip { background: %(elev)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px 8px; }

QFrame#rule { background: %(border)s; border: 0; }
QFrame#hair { background: %(hair)s; border: 0; }

QLabel#secTitle { font-size: %(t_title)spx; font-weight: 600; color: %(white)s; }
QLabel#meta     { font-size: %(t_micro)spx; color: %(text-faint)s; }
QLabel#note     { font-size: %(t_micro)spx; color: %(text-faint)s; }
QLabel#rowKey   { font-size: %(t_body)spx; color: %(text-dim)s; }
QLabel#fieldLabel { font-size: %(t_micro)spx; font-weight: 600; color: %(text-faint)s; }
QLabel#detail   { font-size: %(t_body)spx; color: %(text-dim)s; }
QLabel#detail[state="error"] { color: %(log-err)s; }
QLabel#ready    { font-size: %(t_micro)spx; color: %(green)s; }
QLabel#kbd {
  padding: 0 5px; font-size: %(t_micro)spx; color: %(text-faint)s;
  background: transparent; border: 1px solid %(hair)s; border-radius: %(r)spx;
}

QPushButton#btn {
  height: %(h_ctrl)spx; padding: 0 12px; font-size: %(t_body)spx; font-weight: 500;
  color: %(text)s; background: %(elev)s; border: 1px solid %(border)s; border-radius: %(r)spx;
}
QPushButton#btn:hover    { background: %(elev-hi)s; border-color: %(border-hi)s; color: %(white)s; }
QPushButton#btn:pressed  { background: %(press)s; }
QPushButton#btn:disabled { color: %(text-faint)s; background: %(elev)s; border-color: %(border)s; }
QPushButton#btn[kind="ghost"]       { background: transparent; }
QPushButton#btn[kind="ghost"]:hover { background: %(elev)s; }
QPushButton#btn[kind="primary"] {
  background: %(white)s; color: %(on-white)s; border-color: %(white)s; font-weight: 600;
}
QPushButton#btn[kind="primary"]:hover   { background: %(white-hi)s; border-color: %(white-hi)s; color: %(on-white)s; }
QPushButton#btn[kind="primary"]:pressed { background: %(white-press)s; border-color: %(white-press)s; }
QPushButton#btn[kind="stop"] { background: %(elev-hi)s; color: %(white)s; border-color: %(border-hi)s; font-weight: 600; }
QPushButton#btn[kind="stop"]:hover { background: %(border)s; border-color: %(log-err)s; color: %(white)s; }
QPushButton#btn[size="run"] { height: %(h_run)spx; }

QFrame#segmented { background: %(elev)s; border: 1px solid %(border)s; border-radius: %(r)spx; }
QPushButton#segBtn {
  padding: 0 10px; border: 0; border-radius: %(r_in)spx;
  font-size: %(t_body)spx; color: %(text-faint)s; background: transparent;
}
QPushButton#segBtn:hover   { color: %(text)s; background: %(elev-hi)s; }
QPushButton#segBtn[on="1"] { background: %(elev-hi)s; color: %(white)s; font-weight: 600; }
QPushButton#segBtn:disabled { color: %(text-faint)s; }

QSpinBox {
  height: %(h_ctrl)spx; padding: 0 22px 0 8px; font-size: %(t_body)spx; color: %(text)s;
  background: %(elev)s; border: 1px solid %(border)s; border-radius: %(r)spx;
  selection-background-color: %(border-hi)s; selection-color: %(white)s;
}
QSpinBox:hover { border-color: %(border-hi)s; }
QSpinBox:focus { border-color: %(border-hi)s; background: %(elev-hi)s; }
QSpinBox:disabled { color: %(text-faint)s; }
QSpinBox::up-button, QSpinBox::down-button {
  subcontrol-origin: border; width: 18px; border: 0; background: transparent;
}
QSpinBox::up-button   { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(elev-hi)s; }
QSpinBox::up-arrow   { image: url(%(chev_up)s);   width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url(%(chev_down)s); width: 12px; height: 12px; }

QPlainTextEdit#logBox {
  background: %(sunken)s; border: 1px solid %(border)s; border-radius: %(r)spx;
  color: %(text-dim)s; padding: 6px; selection-background-color: %(sel)s;
}
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical   { background: transparent; width: 8px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle:vertical   { background: %(border-hi)s; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:horizontal { background: %(border-hi)s; border-radius: 4px; min-width: 24px; }
QScrollBar::handle:hover { background: %(text-faint)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMessageBox { background: %(panel)s; }
QMessageBox QLabel { color: %(text)s; }
QMessageBox QPushButton {
  min-width: 72px; height: %(h_ctrl)spx; padding: 0 12px; color: %(text)s;
  background: %(elev)s; border: 1px solid %(border)s; border-radius: %(r)spx;
}
"""


def build_qss() -> str:
    v: dict[str, object] = dict(PALETTE)
    v.update({
        "t_micro": T_MICRO, "t_body": T_BODY, "t_title": T_TITLE,
        "r": RADIUS, "r_in": max(0, RADIUS - 1), "h_ctrl": H_CTRL, "h_run": H_RUN,
        "chev_up": tinted_svg_path("chevron-up", PALETTE["text-faint"], 12),
        "chev_down": tinted_svg_path("chevron-down", PALETTE["text-faint"], 12),
    })
    return _QSS % v


def apply(app) -> None:
    """โหลดฟอนต์ + ตั้ง style/palette/stylesheet ให้ทั้งแอป — เรียกก่อนสร้างหน้าต่าง."""
    load_fonts()
    try:
        app.setStyle("Fusion")
    except Exception:  # pragma: no cover
        pass
    app.setFont(sans_font(T_BODY))
    pal = QPalette()
    for role, key in (
        (QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "elev"), (QPalette.ColorRole.AlternateBase, "elev-hi"),
        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.PlaceholderText, "text-faint"),
        (QPalette.ColorRole.Button, "elev"), (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.Highlight, "border-hi"), (QPalette.ColorRole.HighlightedText, "white"),
        (QPalette.ColorRole.ToolTipBase, "elev"), (QPalette.ColorRole.ToolTipText, "text"),
    ):
        pal.setColor(role, QColor(PALETTE[key]))
    app.setPalette(pal)
    app.setStyleSheet(build_qss())
