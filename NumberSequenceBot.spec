# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — ใช้ไฟล์เดียวกันทั้ง Windows และ macOS

รัน: pyinstaller NumberSequenceBot.spec
ผลลัพธ์: dist/NumberSequenceBot.exe (Windows — ไฟล์เดียวจบ แจกง่าย)
        dist/NumberSequenceBot.app (macOS — .app ต้องเป็นโฟลเดอร์อยู่แล้ว รวมเป็นไฟล์เดียวไม่ได้)

ไฟล์ประกอบ (fonts/, assets/) ต้องแนบไปด้วย ไม่งั้นเปิดมาไม่มีฟอนต์ไทยและไอคอน — ตอนรันจะไปโผล่ที่
sys._MEIPASS ซึ่ง apppaths.resource_dir() ชี้ให้แล้ว
"""
import sys

APP_NAME = "NumberSequenceBot"
IS_MAC = sys.platform == "darwin"

# โมดูลที่ import แบบมีเงื่อนไข/ไม่ตรงไปตรงมา — PyInstaller หาเองไม่เจอ ต้องบอกชื่อไว้
hidden = ["Quartz", "AppKit", "ApplicationServices", "objc"] if IS_MAC else ["keyboard"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("fonts", "fonts"), ("assets", "assets")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # ตัดของหนักที่ไม่ได้ใช้ออก — PySide6 ลากมาทั้งชุดจะได้ไฟล์ใหญ่เกินจำเป็น
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_MAC:
    # .app ต้องเป็นโฟลเดอร์ → แยก EXE/COLLECT/BUNDLE ตามปกติ
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,  # แอปหน้าต่าง — ไม่ต้องเปิด console ค้างไว้
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="cloud.metrabyte.numbersequencebot",
        info_plist={
            # ไม่ใส่ = macOS จะรันแบบขยายภาพ 2 เท่าให้ ทำให้ตัวหนังสือเบลอทั้งแอปบนจอ Retina
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
        },
    )
else:
    # Windows: รวมทุกอย่างไว้ใน .exe ไฟล์เดียว (ส่ง binaries/datas เข้า EXE แล้วไม่ต้องมี COLLECT)
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=False,
    )
