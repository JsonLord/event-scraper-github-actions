import pytest
import json
from pathlib import Path
from datetime import datetime, timedelta
from src.github_auth.cache import AuthCache

def test_cache_set_get_token(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    cache = AuthCache(cache_file=cache_file)

    cache.set_token("test-token", expiry_seconds=3600, method="pat")
    assert cache.get_token() == "test-token"

    # Reload from disk
    cache2 = AuthCache(cache_file=cache_file)
    assert cache2.get_token() == "test-token"

def test_cache_expiry(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    cache = AuthCache(cache_file=cache_file)

    # Set expired token
    cache.set_token("expired-token", expiry_seconds=-10)
    assert cache.get_token() is None

def test_cache_near_expiry(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    cache = AuthCache(cache_file=cache_file)

    cache.set_token("near-token", expiry_seconds=120) # 2 minutes
    assert cache.is_near_expiry(threshold_minutes=5) is True

    cache.set_token("far-token", expiry_seconds=600) # 10 minutes
    assert cache.is_near_expiry(threshold_minutes=5) is False

def test_cache_clear(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    cache = AuthCache(cache_file=cache_file)

    cache.set_token("token", method="pat")
    assert cache_file.exists()

    cache.clear()
    assert cache.get_token() is None
    assert not cache_file.exists()
