from pydantic_settings import BaseSettings

from pathlib import Path
# 反推项目根目录：config.py 位于 backend/ 下，父目录就是根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """配置类（单例）"""
     # ── 大模型（DeepSeek）──
    deepseek_api_key: str   # 必填：DeepSeek 的 API Key
    deepseek_base_url: str = "https://api.deepseek.com/"  # DeepSeek 接口地址

    # 用绝对路径加载环境变量，不依赖运行时的工作目录
    class Config:
        """Pydantic 的元配置：告诉 BaseSettings 该怎么读取配置。"""
        env_file = ENV_FILE          # 从这个文件读取配置
        env_file_encoding = "utf-8"      # 文件编码
        case_sensitive = False           # 大小写不敏感：环境变量 DB_HOST 能对应字段 db_host
        extra = "ignore"                 # .env.local 里多出来的、模型没定义的字段一律忽略（不报错）
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance


# 全局单例
settings = Settings()

