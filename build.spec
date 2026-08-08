# -*- mode: python ; coding: utf-8 -*-
"""
暖宝桌宠 PyInstaller 打包配置

用法:
    conda activate warming_baby
    pyinstaller build.spec

输出:
    dist/暖宝.app
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# 平台检测
IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

# 项目根目录
PROJECT_ROOT = Path('.').resolve()

# 强制收集 chromadb / sentence_transformers / torch (PyInstaller 不会自动收集)
datas_extra = []
binaries_extra = []
hiddenimports_extra = []
collect_packages = ['chromadb', 'transformers', 'torch', 'PyQt6']
for pkg in collect_packages:
    try:
        d, b, h = collect_all(pkg)
        datas_extra += d
        binaries_extra += b
        hiddenimports_extra += h
        print(f"[build.spec] collect_all('{pkg}'): {len(d)} datas, {len(b)} binaries, {len(h)} hiddenimports")
    except Exception as e:
        print(f"[build.spec] WARNING: collect_all('{pkg}') failed: {e}")

# 资源文件列表 (源路径, 目标路径)
datas = [
    # 动画资源
    ('assets/gif_sprites', 'assets/gif_sprites'),
    ('assets/icons', 'assets/icons'),

    # Embedding 模型 (~100MB)
    ('models/bge-small-zh-v1.5', 'models/bge-small-zh-v1.5'),

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

    # Sentence Transformers
    'sentence_transformers',
    'sentence_transformers.models',

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
    'onnxruntime',

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

    # PyTorch 外围库 (只保留 torch 核心)
    'torchvision',
    'torchaudio',
    'torchtext',
    'torchdistx',

    # 大型科学计算库
    'cv2',           # OpenCV (~100MB)
    # pandas/scipy/sklearn/sympy 不能排除: sentence_transformers + transformers 依赖它们

    # HuggingFace 生态 (sentence-transformers 完整导入链需要 datasets)
    # 'transformers',  # 不能排除
    # 'datasets',      # 不能排除: sentence_transformers.base.training_args 依赖
    'diffusers',
    'accelerate',
    'peft',

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
]

# 平台专属排除
if IS_WINDOWS:
    excludes += [
        # macOS 专属
        'AppKit', 'Foundation', 'Cocoa', 'objc',
        'pyobjc', 'pyobjc_core',
        'Foundation', 'AppKit', 'Quartz',
    ]
elif IS_MAC:
    excludes += [
        # Windows 专属 (如有)
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 图标路径 (跨平台)
if IS_MAC:
    icon_path = 'assets/icons/icon.icns'
else:
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
    console=False,          # GUI 应用，不显示终端
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

# macOS: 打包为 .app Bundle; Windows: 跳过 BUNDLE (使用 COLLECT 目录即可)
if IS_MAC:
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
