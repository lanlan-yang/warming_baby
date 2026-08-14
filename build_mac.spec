# -*- mode: python ; coding: utf-8 -*-
"""
暖宝桌宠 PyInstaller 打包配置 (macOS)

用法:
    conda activate warming_baby
    unalias python  # macOS 必须去除 python 别名
    python -m PyInstaller build_mac.spec

输出:
    dist/暖宝.app
"""

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
        print(f"[build_mac.spec] collect_all('{pkg}'): {len(d)} datas, {len(b)} binaries, {len(h)} hiddenimports")
    except Exception as e:
        print(f"[build_mac.spec] WARNING: collect_all('{pkg}') failed: {e}")

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

    # Windows 专属模块 (macOS 打包时排除，如有)
]

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries_extra,
    datas=datas + datas_extra,
    hiddenimports=hiddenimports + hiddenimports_extra,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

# 瘦身: 从收集的二进制文件中过滤掉不需要的大 DLL
_bin_exclude_names: set[str] = set()
if _bin_exclude_names:
    a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in _bin_exclude_names]
    print(f"[build_mac.spec] 瘦身: 过滤掉 {len(_bin_exclude_names)} 个大 DLL")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    icon='assets/icons/icon.icns',
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

# macOS: 打包为 .app Bundle
app = BUNDLE(
    coll,
    name='暖宝.app',
    icon='assets/icons/icon.icns',
    bundle_identifier='com.warmbaby.app',
    info_plist={
        'CFBundleName': '暖宝',
        'CFBundleDisplayName': '暖宝',
        'CFBundleShortVersionString': '0.5.8',
        'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '10.15',
        'NSHighResolutionCapable': True,
        'LSUIElement': True,  # 不在 Dock 显示 (桌宠应用)
    },
)
