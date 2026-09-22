"""ของใช้ร่วมระหว่างหน้าจอ: ธีม (โทนเดียวกับบอทเรียงเลข) และตัวรันงาน block ใน thread แยก."""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

QSS = """
QWidget { background: #0a0a0a; color: #ededed; font-family: 'Segoe UI'; font-size: 13px; }
QLabel#title { font-size: 17px; font-weight: 600; }
QLabel#step { color: #22c55e; font-weight: 600; }
QLabel#dim { color: #808080; font-size: 12px; }
QLabel#error { color: #f87171; }
QPushButton {
  background: #161618; border: 1px solid #262628; border-radius: 8px;
  padding: 7px 14px; color: #ededed;
}
QPushButton:hover { background: #1f1f22; border-color: #3a3a3d; }
QPushButton:pressed { background: #0e0e10; }
QPushButton:disabled { color: #5a5a5d; border-color: #1c1c1e; }
QPushButton#primary { background: #22c55e; color: #0a0a0a; font-weight: 600; border: none; }
QPushButton#primary:hover { background: #16a34a; }
QPushButton#primary:disabled { background: #1f3d2a; color: #5f7f69; }
QLineEdit, QComboBox {
  background: #161618; border: 1px solid #262628; border-radius: 6px; padding: 6px 8px;
  selection-background-color: #22c55e; selection-color: #0a0a0a;
}
QLineEdit:focus, QComboBox:focus { border-color: #22c55e; }
QComboBox QAbstractItemView { background: #161618; border: 1px solid #262628; selection-background-color: #1f3d2a; }
QListWidget {
  background: #070708; border: 1px solid #262628; border-radius: 8px; padding: 4px;
}
QListWidget::item { padding: 8px 6px; border-radius: 6px; }
QListWidget::item:selected { background: #1f3d2a; color: #ededed; }
QFrame#card { background: #0f0f11; border: 1px solid #1f1f22; border-radius: 10px; }
QFrame#card QLabel, QFrame#card QWidget#row { background: transparent; }
QPlainTextEdit {
  background: #070708; border: 1px solid #262628; border-radius: 8px;
  font-family: 'JetBrains Mono','Consolas',monospace; font-size: 12px; color: #a0a0a0;
}
QToolBar { background: #111113; border: none; border-left: 1px solid #1f1f22; spacing: 2px; padding: 6px 4px; }
QToolButton { border: none; border-radius: 8px; padding: 6px; }
QToolButton:hover { background: #1f1f22; }
QToolButton:pressed { background: #2a2a2d; }
QToolButton:checked { background: #1f3d2a; }
QStatusBar { background: #111113; color: #a0a0a0; border-top: 1px solid #1f1f22; }
QStatusBar QLabel { background: transparent; color: #a0a0a0; }
QToolTip { background: #161618; color: #ededed; border: 1px solid #262628; padding: 4px 6px; }
"""


class _Bridge(QObject):
    done = Signal(object)
    error = Signal(str)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None],
              on_error: Callable[[str], None], parent: Optional[QObject] = None) -> None:
    """รัน fn ใน thread แยก แล้วเรียก on_done/on_error กลับบน GUI thread (ผ่าน queued signal)."""
    bridge = _Bridge(parent)
    bridge.done.connect(on_done)
    bridge.error.connect(on_error)
    bridge.done.connect(bridge.deleteLater)
    bridge.error.connect(bridge.deleteLater)

    def work() -> None:
        try:
            result = fn()
        except Exception as e:
            bridge.error.emit(str(e) or e.__class__.__name__)
            return
        bridge.done.emit(result)

    threading.Thread(target=work, daemon=True).start()
