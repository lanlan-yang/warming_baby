"""
secure.py - 安全存储层

使用本地 JSON 文件存储敏感信息 (如 API Key)。
为避免 macOS 钥匙串弹窗，不使用 keyring。
"""
import json
from pathlib import Path
from typing import Optional

from .storage import get_config_dir

FALLBACK_FILE = get_config_dir() / '.secrets.json'


class SecureStorage:
    """安全存储类 - 使用本地 JSON 文件"""

    def __init__(self):
        self._data = self._load_data()

    def is_available(self) -> bool:
        return True

    def get_storage_type(self) -> str:
        return "local"

    def save_api_key(self, api_key: str) -> bool:
        if not api_key or not api_key.strip():
            return self.delete_api_key()
        return self._save('llm_api_key', api_key.strip())

    def load_api_key(self) -> str:
        return self._load('llm_api_key') or ""

    def delete_api_key(self) -> bool:
        return self._delete('llm_api_key')

    def has_api_key(self) -> bool:
        return bool(self.load_api_key())

    # ==================== Embedding API Key ====================

    def save_embedding_api_key(self, api_key: str) -> bool:
        if not api_key or not api_key.strip():
            return self.delete_embedding_api_key()
        return self._save("embedding_api_key", api_key.strip())

    def load_embedding_api_key(self) -> str:
        return self._load("embedding_api_key") or ""

    def delete_embedding_api_key(self) -> bool:
        return self._delete("embedding_api_key")

    def has_embedding_api_key(self) -> bool:
        return bool(self.load_embedding_api_key())

    def save_secret(self, name: str, value: str) -> bool:
        if not name or not value:
            return False
        return self._save(name, value)

    def load_secret(self, name: str) -> Optional[str]:
        return self._load(name)

    def delete_secret(self, name: str) -> bool:
        return self._delete(name)

    def _load_data(self) -> dict:
        if not FALLBACK_FILE.exists():
            return {}
        try:
            with open(FALLBACK_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_data(self) -> bool:
        try:
            FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FALLBACK_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            FALLBACK_FILE.chmod(0o600)
            return True
        except Exception as e:
            print(f"Error: Failed to save secrets: {e}")
            return False

    def _save(self, name: str, value: str) -> bool:
        self._data[name] = value
        return self._save_data()

    def _load(self, name: str) -> Optional[str]:
        return self._data.get(name)

    def _delete(self, name: str) -> bool:
        if name in self._data:
            del self._data[name]
            return self._save_data()
        return True


secure_storage = SecureStorage()
