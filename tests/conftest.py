"""Installed HTTP dependency must precede legacy optional-import shims.

Older extraction tests use sys.modules.setdefault('requests', a placeholder).
Qualification/provider tests exercise response failures using fake transports,
so retain the real requests exception types without making network requests.
"""
import requests  # noqa: F401
