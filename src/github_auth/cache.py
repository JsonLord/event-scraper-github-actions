import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

CACHE_DIR = Path.home() / ".cache" / "event-scraper-github-actions"
CACHE_FILE = CACHE_DIR / "auth_cache.json"

class AuthCache:
    def __init__(self, cache_file: Path = CACHE_FILE):
        self.cache_file = cache_file
        self._memory_cache: Optional[Dict[str, Any]] = None
        self._load_from_disk()

    def _load_from_disk(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    self._memory_cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._memory_cache = None

    def _save_to_disk(self):
        self.cache_dir = self.cache_file.parent
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.cache_file, "w") as f:
                json.dump(self._memory_cache, f)
        except IOError:
            # We can log this or ignore it as it's a cache
            pass

    def get_token(self) -> Optional[str]:
        if not self._memory_cache:
            return None

        expiry_str = self._memory_cache.get("expiry")
        if expiry_str:
            expiry = datetime.fromisoformat(expiry_str)
            if datetime.now() >= expiry:
                return None

        return self._memory_cache.get("token")

    def set_token(self, token: str, expiry_seconds: Optional[int] = None, method: str = "pat"):
        expiry = None
        if expiry_seconds is not None:
            expiry = (datetime.now() + timedelta(seconds=expiry_seconds)).isoformat()

        self._memory_cache = {
            "token": token,
            "expiry": expiry,
            "method": method,
            "updated_at": datetime.now().isoformat()
        }
        self._save_to_disk()

    def clear(self):
        self._memory_cache = None
        if self.cache_file.exists():
            try:
                self.cache_file.unlink()
            except IOError:
                pass

    def is_near_expiry(self, threshold_minutes: int = 5) -> bool:
        if not self._memory_cache or not self._memory_cache.get("expiry"):
            return False

        expiry = datetime.fromisoformat(self._memory_cache["expiry"])
        return datetime.now() + timedelta(minutes=threshold_minutes) >= expiry
