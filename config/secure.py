"""
secure.py - 安全存储层

使用系统密钥环 (Keyring) 安全存储敏感信息 (如 API Key)
"""
from pathlib import Path
from typing import Optional
import base64

# 尝试导入 keyring
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

from .storage import get_config_dir

SERVICE_NAME = "WarmBaby"
USERNAME_API_KEY = "llm_api_key"
FALLBACK_FILE = get_config_dir() / '.secrets.json'


class SecureStorage:
    """安全存储类"""

    def __init__(self):
        self._use_keyring = KEYRING_AVAILABLE
        self._fallback_data = self._load_fallback_file()

    def is_available(self) -> bool:
        return True

    def get_storage_type(self) -> str:
        return "keyring" if self._use_keyring else "fallback"

    def save_api_key(self, api_key: str) -> bool:
        if not api_key or not api_key.strip():
            return self.delete_api_key()
        api_key = api_key.strip()
        if self._use_keyring:
            return self._save_keyring(USERNAME_API_KEY, api_key)
        else:
            return self._save_fallback(USERNAME_API_KEY, api_key)

    def load_api_key(self) -> str:
        if self._use_keyring:
            return self._load_keyring(USERNAME_API_KEY) or ""
        else:
            return self._load_fallback(USERNAME_API_KEY) or ""

    def delete_api_key(self) -> bool:
        if self._use_keyring:
            return self._delete_keyring(USERNAME_API_KEY)
        else:
            return self._delete_fallback(USERNAME_API_KEY)

    def has_api_key(self) -> bool:
        return bool(self.load_api_key())

    def save_secret(self, name: str, value: str) -> bool:
        if not name or not value:
            return False
        if self._use_keyring:
            return self._save_keyring(name, value)
        else:
            return self._save_fallback(name, value)

    def load_secret(self, name: str) -> Optional[str]:
        if self._use_keyring:
            return self._load_keyring(name)
        else:
            return self._load_fallback(name)

    def delete_secret(self, name: str) -> bool:
        if self._use_keyring:
            return self._delete_keyring(name)
        else:
            return self._delete_fallback(name)

    def _save_keyring(self, name: str, value: str) -> bool:
        try:
            keyring.set_password(SERVICE_NAME, name, value)
            return True
        except Exception as e:
            print(f"Warning: Failed to save to keyring: {e}")
            self._use_keyring = False
            return self._save_fallback(name, value)

    def _load_keyring(self, name: str) -> Optional[str]:
        try:
            return keyring.get_password(SERVICE_NAME, name)
        except Exception as e:
            print(f"Warning: Failed to load from keyring: {e}")
            self._use_keyring = False
            return self._load_fallback(name)

    def _delete_keyring(self, name: str) -> bool:
        try:
            if keyring.get_password(SERVICE_NAME, name):
                keyring.delete_password(SERVICE_NAME, name)
            return True
        except Exception as e:
            print(f"Warning: Failed to delete from keyring: {e}")
            return self._delete_fallback(name)

    def _load_fallback_file(self) -> dict:
        import json
        if not FALLBACK_FILE.exists():
            return {}
        try:
            with open(FALLBACK_FILE, 'r') as f:
                data = json.load(f)
            return {k: self._decode(v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_fallback(self, name: str, value: str) -> bool:
        import json
        try:
            self._fallback_data[name] = value
            encoded = {k: self._encode(v) for k, v in self._fallback_data.items()}
            with open(FALLBACK_FILE, 'w') as f:
                json.dump(encoded, f, indent=2)
            FALLBACK_FILE.chmod(0o600)
            return True
        except Exception as e:
            print(f"Error: Failed to save fallback: {e}")
            return False

    def _load_fallback(self, name: str) -> Optional[str]:
        return self._fallback_data.get(name)

    def _delete_fallback(self, name: str) -> bool:
        import json
        try:
            if name in self._fallback_data:
                del self._fallback_data[name]
                encoded = {k: self._encode(v) for k, v in self._fallback_data.items()}
                with open(FALLBACK_FILE, 'w') as f:
                    json.dump(encoded, f, indent=2)
            return True
        except Exception:
            return False

    def _encode(self, value: str) -> str:
        return base64.b64encode(value.encode()).decode()

    def _decode(self, value: str) -> str:
        try:
            return base64.b64decode(value.encode()).decode()
        except Exception:
            return value


secure_storage = SecureStorage()
