# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — ใช้ไฟล์เดียวกันทั้ง Windows และ macOS

รัน: pyinstaller NumberSequenceBot.spec
ผลลัพธ์: dist/NumberSequenceBot.exe (Windows — ไฟล์เดียวจบ แจกง่าย)
        dist/NumberSequenceBot.app (macOS — .app ต้องเป็นโฟลเดอร์อยู่แล้ว รวมเป็นไฟล์เดียวไม่ได้)

ไฟล์ประกอบ (fonts/, assets/) ต้องแนบไปด้วย ไม่งั้นเปิดมาไม่มีฟอนต์ไทยและไอคอน — ตอนรันจะไปโผล่ที่
sys._MEIPASS ซึ่ง apppaths.resource_dir() ชี้ให้แล้ว
"""
import glob
import os
import shutil
import sys

APP_NAME = "NumberSequenceBot"
IS_MAC = sys.platform == "darwin"


def tesseract_payload():
    """หา Tesseract ที่ติดตั้งในเครื่องที่กำลัง build แล้วแนบไปกับโปรแกรม

    คืน (binaries, datas) ให้ Analysis — ตัวโปรแกรมไปอยู่ใน `tesseract/` และไฟล์ภาษาอยู่ใน `tessdata/`
    ตรงกับที่ capture.bundled_tesseract() กับ TESSDATA_PREFIX ชี้ไว้

    Windows: ต้องหอบ DLL ข้างๆ tesseract.exe ไปไว้โฟลเดอร์เดียวกันด้วยเอง — Windows หา DLL จาก
    โฟลเดอร์ของไฟล์ที่รันก่อนเสมอ ถ้าปล่อยให้ PyInstaller เอาไปกองที่ราก tesseract.exe จะหาไม่เจอ
    macOS: ปล่อยให้ PyInstaller ไล่ dylib (libtesseract/leptonica/libarchive + ลูกอีก 15 ตัว) แล้ว
    แก้ path ให้เอง
    """
    exe = shutil.which("tesseract")
    if not exe:
        for guess in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                      "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
            if os.path.isfile(guess):
                exe = guess
                break
    if not exe:
        raise SystemExit("build ไม่ได้: หา tesseract ในเครื่องไม่เจอ (ต้องติดตั้งก่อน build)")
    exe = os.path.realpath(exe)
    exe_dir = os.path.dirname(exe)

    # ไฟล์ภาษา: ตาม TESSDATA_PREFIX ก่อน แล้วค่อยที่มาตรฐานของแต่ละระบบ
    prefix = os.path.dirname(exe_dir)  # .../bin → ...
    for folder in (os.environ.get("TESSDATA_PREFIX", ""),
                   os.path.join(prefix, "share", "tessdata"),
                   os.path.join(exe_dir, "tessdata"),
                   "/opt/homebrew/share/tessdata", "/usr/local/share/tessdata"):
        if folder and os.path.isfile(os.path.join(folder, "eng.traineddata")):
            tessdata = folder
            break
    else:
        raise SystemExit("build ไม่ได้: หา eng.traineddata ไม่เจอ")

    binaries = [(exe, "tesseract")]
    if sys.platform == "win32":
        binaries += [(dll, "tesseract") for dll in glob.glob(os.path.join(exe_dir, "*.dll"))]
    # เอาเฉพาะ eng — บอทอ่านแต่ตัวเลข ภาษาอื่นมีแต่ทำให้ไฟล์ใหญ่ฟรีๆ
    datas = [(os.path.join(tessdata, "eng.traineddata"), "tessdata")]
    return binaries, datas


TESS_BINARIES, TESS_DATAS = tesseract_payload()

# โมดูลที่ import แบบมีเงื่อนไข/ไม่ตรงไปตรงมา — PyInstaller หาเองไม่เจอ ต้องบอกชื่อไว้
hidden = ["Quartz", "AppKit", "ApplicationServices", "objc"] if IS_MAC else ["keyboard"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=TESS_BINARIES,
    datas=[("fonts", "fonts"), ("assets", "assets")] + TESS_DATAS,
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
            "CFBundleShortVersionString": "1.0.1",
            "CFBundleVersion": "1.0.1",
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
