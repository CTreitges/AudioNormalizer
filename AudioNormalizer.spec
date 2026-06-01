# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Gebündelte FFmpeg-Binary (imageio-ffmpeg) + Icon mitnehmen.
# Nur das binaries/-Verzeichnis einsammeln (nicht den ganzen Paket-Datenbestand);
# imageio_ffmpeg.get_ffmpeg_exe() löst die Binary ab 0.5.0 über
# importlib.resources gegen das Subpaket imageio_ffmpeg.binaries auf -> dieses
# muss explizit als Hidden-Import mit. (Der Auto-Hook von hooks-contrib täte das
# zwar auch, aber wir machen es selbst-enthaltend.)
datas = [('icon.ico', '.')]
datas += collect_data_files('imageio_ffmpeg', subdir='binaries')

# Eigene Submodule (GUI wird dynamisch geladen) + imageio-Binary-Subpaket.
hiddenimports = collect_submodules('audionormalizer') + ['imageio_ffmpeg.binaries']

a = Analysis(
    ['normalizer.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AudioNormalizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
