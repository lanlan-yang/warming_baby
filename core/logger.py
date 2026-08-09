"""
logger - 日志

Usage:
    from core.logger import logger, setup_logger
"""
import sys
from pathlib import Path

from loguru import logger

from core.platform import IS_MAC, IS_WINDOWS


def _get_app_dir() -> Path:
    """获取应用数据目录 (避免循环导入)

    开发环境：项目根目录 tmp/（与 paths.get_app_dir 保持一致）
    打包后：系统标准目录
    """
    if not getattr(sys, 'frozen', False):
        # 开发环境：项目根目录下的 tmp/
        base = Path(__file__).resolve().parent.parent / 'tmp'
    else:
        # 打包后：系统标准目录
        if IS_MAC:
            base = Path.home() / 'Library' / 'Application Support' / 'WarmBaby'
        elif IS_WINDOWS:
            base = Path.home() / 'AppData' / 'Roaming' / 'WarmBaby'
        else:
            base = Path(__file__).resolve().parent.parent / 'data'
    base.mkdir(parents=True, exist_ok=True)
    return base


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = _get_app_dir() / 'logs'


def setup_logger(
    *,
    console_level='WARNING',
    file_log_level='INFO',
    log_file='api_service.log',
    rotation='100 MB',
    retention='7 days',
    compression='zip',
    serialize=False,
):
    """初始化日志系统"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    # 配置控制台日志 (打包后 GUI 模式 sys.stderr 为 None，跳过)
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=console_level,
            colorize=True,
            backtrace=True,
            diagnose=False,
        )
    # 配置日志文件
    logger.add(
        LOG_DIR / log_file,
        level=file_log_level,     # 日志级别
        rotation=rotation,        # 日志切割策略（时间、大小）
        retention=retention,      # 日志保留策略
        compression=compression,  # 旧日志压缩格式
        serialize=serialize,      # 是否输出 JSON 格式
        enqueue=True,             # 是否异步写入
        catch=True,               # 捕获日志异常
        encoding='utf-8',
        backtrace=True,           # 是否追踪异常（异常栈）
        diagnose=False,           # 是否显示变量诊断
    )
    return logger
