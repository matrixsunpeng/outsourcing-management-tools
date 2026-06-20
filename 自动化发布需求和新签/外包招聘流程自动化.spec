# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('F:\\ClaudeCode\\外包工具箱\\自动化发布需求和新签\\1.提取申请单建多维表', '1.提取申请单建多维表'), ('F:\\ClaudeCode\\外包工具箱\\自动化发布需求和新签\\2.根据多维表发布需求', '2.根据多维表发布需求'), ('F:\\ClaudeCode\\外包工具箱\\自动化发布需求和新签\\3.查找需求返回职位编号', '3.查找需求返回职位编号')]
binaries = []
hiddenimports = ['playwright', 'playwright.sync_api', 'openpyxl', 'xlrd', 'dotenv', 'python-dotenv', 'requests', 'docx', 'python-docx', 'json', 'io', 'runpy', 'argparse', 'getpass', 'msvcrt', 'datetime', 'pathlib', 'urllib', 're', 'tempfile', 'time']
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['F:\\ClaudeCode\\外包工具箱\\自动化发布需求和新签\\gui.py'],
    pathex=[],
    binaries=binaries,
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
    [],
    exclude_binaries=True,
    name='外包招聘流程自动化',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='外包招聘流程自动化',
)
