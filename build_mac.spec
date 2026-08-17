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

# 用户级 site-packages（某些包如 chromadb 装在 ~/.local 下而非 conda 环境）
USER_SITE = Path.home() / '.local' / 'lib' / 'python3.13' / 'site-packages'
PATH_EXTRAS = [str(PROJECT_ROOT)]
if USER_SITE.is_dir():
    PATH_EXTRAS.append(str(USER_SITE))
    print(f"[build_mac.spec] 添加用户 site-packages 到 pathex: {USER_SITE}")

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
# 注意：只打包运行时需要的图标，排除原始设计稿 (*.png 原图)
datas = [
    # 动画资源 (gif 精灵图)
    ('assets/gif_sprites', 'assets/gif_sprites'),
    # icons 目录 (只打包运行时需要的图标文件)
    ('assets/icons/icon.icns', 'assets/icons'),
    ('assets/icons/app', 'assets/icons/app'),
    ('assets/icons/tray', 'assets/icons/tray'),
    ('assets/icons/favicon_128.ico', 'assets/icons'),
    ('assets/icons/favicon _256.ico', 'assets/icons/favicon _256.ico'),

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
    'click',  # uvicorn 依赖

    # aiohttp 网络栈 (PyInstaller 不会自动检测 C 扩展依赖)
    'aiohttp',
    'aiohttp.connector',
    'aiohttp.client',
    'aiohttp.http_parser',
    'aiohttp._http_parser',
    'yarl',
    'yarl._url',
    'multidict',
    'multidict._multidict',
    'async_timeout',
    'frozenlist',
    'frozenlist._frozenlist',
    'charset_normalizer',
    'charset_normalizer.md',

    # SSL 证书 (aiohttp 用 certifi 的 CA bundle)
    'certifi',
    'ssl',

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
    'datasets',
    'tokenizers',
    'huggingface_hub',
    'safetensors',

    # 浏览器自动化 (项目未使用，chromadb 间接拉入)
    'playwright',

    # PDF 处理 (项目未使用)
    'pymupdf',
    'fitz',

    # gRPC (chromadb 遥测用，已禁用 anonymized_telemetry=False)
    'grpc',
    'grpcio',

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
    pathex=PATH_EXTRAS,
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

# 瘦身: 从收集的二进制文件中过滤掉不需要的大 framework / DLL
# 即使 excludes 排除了 .pyd，对应的 Qt framework 仍可能被 collect_all('PyQt6') 拉入
_qt_fw_exclude = {
    # Qt3D 全家桶
    'Qt3DCore', 'Qt3DRender', 'Qt3DAnimation', 'Qt3DInput', 'Qt3DLogic', 'Qt3DExtras',
    # QtQuick / QML（桌宠不用 QML）
    'QtQuick', 'QtQuick3D', 'QtQml', 'QtQmlModels', 'QtQmlMeta', 'QtQmlWorkerScript',
    'QtQuickControls2', 'QtQuickTemplates2', 'QtQuickDialogs2',
    'QtQuick3DParticles', 'QtQuick3DPhysics', 'QtQuick3DRuntimeRender',
    'QtQuickShapes', 'QtQuickTimeline', 'QtQuick3DAssetUtils',
    # QtMultimedia（桌宠不播视频/音频）
    'QtMultimedia', 'QtMultimediaWidgets',
    # QtPdf（不查看 PDF）
    'QtPdf', 'QtPdfWidgets',
    # QtVirtualKeyboard（不用虚拟键盘）
    'QtVirtualKeyboard',
    # QtDesigner（不用设计器）
    'QtDesigner',
}
_bin_exclude_names: set[str] = _qt_fw_exclude
if _bin_exclude_names:
    before = len(a.binaries)
    a.binaries = [b for b in a.binaries if Path(b[0]).name not in _bin_exclude_names]
    print(f"[build_mac.spec] 瘦身: 过滤掉 {before - len(a.binaries)} 个 Qt framework")

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
    upx=True,             # 启用 UPX 压缩可执行文件
    console=False,        # 关闭控制台窗口（桌宠应用无需终端）
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
    upx=True,             # 启用 UPX 压缩 DLL/dylib
    upx_exclude=[],      # 不排除任何文件，全部尝试压缩
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
        'CFBundleShortVersionString': '0.7.1',
        'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '10.15',
        'NSHighResolutionCapable': True,
        'LSUIElement': True,  # 不在 Dock 显示 (桌宠应用)
    },
)
