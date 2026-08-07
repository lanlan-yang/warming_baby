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

block_cipher = None

# 项目根目录
PROJECT_ROOT = Path('.').resolve()

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
    'pandas',        # 数据分析 (~30MB)
    'scipy',         # 科学计算 (~50MB)
    'sklearn',       # 机器学习 (~30MB)
    'scikit-learn',
    'sympy',

    # HuggingFace 生态 (只用到 sentence-transformers)
    # 'transformers',  # 不能排除，sentence-transformers 依赖它
    'datasets',
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
]

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
