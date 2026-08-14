# -*- mode: python ; coding: utf-8 -*-
"""
暖宝桌宠 PyInstaller 打包配置 (Windows)

用法:
    conda activate warming_baby
    pyinstaller build_win.spec

输出:
    dist/暖宝/暖宝.exe
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 项目根目录
PROJECT_ROOT = Path('.').resolve()

# 强制收集 chromadb / PyQt6 (PyInstaller 不会自动收集)
datas_extra = []
binaries_extra = []
hiddenimports_extra = []
collect_packages = ['chromadb', 'PyQt6']
for pkg in collect_packages:
    try:
        d, b, h = collect_all(pkg)
        datas_extra += d
        binaries_extra += b
        hiddenimports_extra += h
        print(f"[build_win.spec] collect_all('{pkg}'): {len(d)} datas, {len(b)} binaries, {len(h)} hiddenimports")
    except Exception as e:
        print(f"[build_win.spec] WARNING: collect_all('{pkg}') failed: {e}")

# 强制使用当前 conda 环境的 SSL DLL（避免从 base 环境打包旧版本导致 _ssl 加载失败）
_conda_prefix = Path(sys.prefix)
_ssl_dlls = [
    _conda_prefix / 'Library' / 'bin' / 'libssl-3-x64.dll',
    _conda_prefix / 'Library' / 'bin' / 'libcrypto-3-x64.dll',
]
for dll in _ssl_dlls:
    if dll.exists():
        binaries_extra.append((str(dll), '.'))
        print(f"[build_win.spec] 强制包含 SSL DLL: {dll}")
    else:
        print(f"[build_win.spec] WARNING: SSL DLL 不存在: {dll}")

# 强制将 PyQt6 的 Qt6 核心 DLL 复制到 _internal/ 根目录
# 解决 QtWidgets.pyd 等 Python 绑定无法在 Qt6/bin/ 子目录找到 DLL 的问题
# 同时设置 runtime hook 确保 DLL 搜索路径正确
_pyqt6_root = Path(sys.prefix) / 'Lib' / 'site-packages' / 'PyQt6'
if _pyqt6_root.exists():
    _qt6_bin = _pyqt6_root / 'Qt6' / 'bin'
    # 只复制 SSL 和 ICU 相关 DLL，不复制 Qt6 核心 DLL（避免版本冲突）
    # Qt6 DLL 由 collect_all('PyQt6') 收集到 PyQt6/Qt6/bin/，通过 runtime hook 查找
    _extra_dlls = [
        'opengl32sw.dll',
        'd3dcompiler_47.dll',
    ]
    for dll_name in _extra_dlls:
        dll_path = _qt6_bin / dll_name
        if dll_path.exists():
            binaries_extra.append((str(dll_path), '.'))
    print(f"[build_win.spec] 已将 {len(_extra_dlls)} 个补充 DLL 复制到 _internal/ 根目录")
else:
    print(f"[build_win.spec] WARNING: PyQt6 目录不存在: {_pyqt6_root}")

# Runtime hook: 让 Windows 能在 PyQt6/Qt6/bin 子目录找到 Qt6 DLL
_runtime_hook_code = '''
import sys
import os
if sys.platform == 'win32':
    _internal = os.path.join(os.path.dirname(sys.executable), '_internal')
    print(f"[runtime_hook] _internal = {_internal}", flush=True)
    print(f"[runtime_hook] exists = {os.path.isdir(_internal)}", flush=True)
    # 必须先添加 _internal/ 根目录，确保 MSVCP140.dll 等VC运行库
    # 优先于系统 PATH 中的 conda base 旧版本
    if os.path.isdir(_internal):
        os.environ['PATH'] = _internal + os.pathsep + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(_internal)
            print(f"[runtime_hook] added _internal to dll dirs", flush=True)
    _qt6_bin = os.path.join(_internal, 'PyQt6', 'Qt6', 'bin')
    if os.path.isdir(_qt6_bin):
        os.environ['PATH'] = _qt6_bin + os.pathsep + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(_qt6_bin)
    _pyqt6_dir = os.path.join(_internal, 'PyQt6')
    if os.path.isdir(_pyqt6_dir):
        os.environ['PATH'] = _pyqt6_dir + os.pathsep + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(_pyqt6_dir)
    print(f"[runtime_hook] done", flush=True)
'''
import tempfile
_runtime_hook_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
_runtime_hook_file.write(_runtime_hook_code)
_runtime_hook_file.close()
print(f"[build_win.spec] Runtime hook: {_runtime_hook_file.name}")

# 资源文件列表 (源路径, 目标路径)
datas = [
    # 动画资源
    ('assets/gif_sprites', 'assets/gif_sprites'),
    ('assets/icons', 'assets/icons'),

    # 记忆系统配置
    ('memory/res', 'memory/res'),
]

# 隐藏导入 (PyInstaller 无法自动检测的依赖)
hiddenimports = [
    # ChromaDB
    'chromadb',
    'chromadb.config',
    'chromadb.api',
    'chromadb.api.segment',
    'chromadb.db',
    'chromadb.db.impl',
    'chromadb.db.impl.sqlite',
    'chromadb.segment',
    'chromadb.segment.impl',
    'chromadb.segment.impl.vector',
    'chromadb.segment.impl.metadata',
    'chromadb.telemetry',
    'chromadb.utils',
    'chromadb.utils.embedding_functions',

    # LangChain
    'langchain',
    'langchain_core',
    'langchain_core.messages',
    'langchain_core.prompts',
    'langchain_core.output_parsers',
    'langchain_community',

    # LangGraph
    'langgraph',
    'langgraph.graph',
    'langgraph.prebuilt',

    # 其他
    'pydantic',
    'pydantic_settings',
    'qasync',
    'yaml',

    # PyQt6 QtNetwork (QLocalServer/QLocalSocket)
    'PyQt6.QtNetwork',
]

# 排除的模块 (不需要打包)
excludes = [
    # 测试 & 文档
    'test',
    'tests',
    'pytest',
    'matplotlib',
    'tkinter',
    'IPython',
    'notebook',
    'jupyter',
    'sphinx',
    'docutils',

    # PyTorch & 本地模型 (已改用云端 embedding，不再需要)
    'torch',
    'torchvision',
    'torchaudio',
    'torchtext',
    'torchdistx',
    'transformers',
    'sentence_transformers',

    # 大型科学计算库
    'cv2',           # OpenCV (~100MB)
    # pandas/scipy/sklearn 暂保留: chromadb 可能间接依赖

    # HuggingFace 生态 (已移除本地 embedding，不再需要)
    'diffusers',
    'accelerate',
    'peft',
    'onnxruntime',

    # 其他不必要的大型库
    'pyarrow',
    'arrow',
    'fastparquet',
    'pygame',
    'moviepy',
    'imageio',

    # PyQt6 未使用的子模块 (项目只用 QtCore/QtGui/QtWidgets/QtNetwork)
    # 排除这些可减少 ~300MB Qt6 DLL + 对应 .pyd
    'PyQt6.QtBluetooth',
    'PyQt6.QtDBus',
    'PyQt6.QtDesigner',
    'PyQt6.QtHelp',
    'PyQt6.QtMultimedia',
    'PyQt6.QtMultimediaWidgets',
    'PyQt6.QtNfc',
    'PyQt6.QtPdf',
    'PyQt6.QtPdfWidgets',
    'PyQt6.QtPositioning',
    'PyQt6.QtPrintSupport',
    'PyQt6.QtQml',
    'PyQt6.QtQuick',
    'PyQt6.QtQuick3D',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtRemoteObjects',
    'PyQt6.QtSensors',
    'PyQt6.QtSerialPort',
    'PyQt6.QtSpatialAudio',
    'PyQt6.QtSql',
    'PyQt6.QtStateMachine',
    'PyQt6.QtSvg',
    'PyQt6.QtSvgWidgets',
    'PyQt6.QtTest',
    'PyQt6.QtTextToSpeech',
    'PyQt6.QtWebChannel',
    'PyQt6.QtWebSockets',
    'PyQt6.QtXml',
    'PyQt6.QAxContainer',

    # macOS 专属模块 (Windows 打包时排除)
    'AppKit',
    'Foundation',
    'Cocoa',
    'Quartz',
    'objc',
    'pyobjc',
    'pyobjc_core',
]

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries_extra,
    datas=datas + datas_extra,
    hiddenimports=hiddenimports + hiddenimports_extra,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[_runtime_hook_file.name],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 瘦身: 从收集的二进制文件中过滤掉不需要的大 DLL
# 注意: opengl32sw.dll 不能移除，Qt6Gui 依赖它做软件渲染兜底
_bin_exclude_names: set[str] = set()
if _bin_exclude_names:
    a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in _bin_exclude_names]
    print(f"[build_win.spec] 瘦身: 过滤掉 {len(_bin_exclude_names)} 个大 DLL")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 图标路径
icon_path = 'assets/icons/favicon _256.ico' if Path('assets/icons/favicon _256.ico').exists() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='暖宝',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 关闭控制台窗口（桌宠应用无需终端）
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='暖宝',
)

# Windows: 使用 COLLECT 目录即可，不需要 BUNDLE
