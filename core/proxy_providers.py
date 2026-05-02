"""Dynamic proxy IP providers — concrete implementations moved to providers/proxy/

Supports two modes:
  1. Static proxy: reads fixed proxy list from database (existing logic)
  2. Dynamic proxy: fetches proxy IPs from third-party API in real time

Dynamic proxy providers are configured via provider_settings; if not configured, falls back to static proxy pool.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class BaseProxyProvider(ABC):
    """Dynamic proxy provider base class."""

    @abstractmethod
    def get_proxy(self) -> Optional[str]:
        """Get a proxy URL, format: http://host:port or http://user:pass@host:port.
        Returns None if no proxy is available."""
        ...


# ---------------------------------------------------------------------------
# Lazy re-exports for backward compatibility
# (concrete classes now live under providers/proxy/)
# ---------------------------------------------------------------------------
_LAZY_IMPORTS = {
    "ApiExtractProvider": "providers.proxy.api_extract",
    "RotatingProxyProvider": "providers.proxy.rotating_gateway",
}


def __getattr__(name: str):
    module_path = _LAZY_IMPORTS.get(name)
    if module_path is not None:
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_proxy_provider(provider_key: str, config: dict) -> BaseProxyProvider:
    """Create a proxy provider based on provider_key and configuration."""
    if provider_key == "api_extract":
        api_url = config.get("proxy_api_url", "")
        if not api_url:
            raise RuntimeError("Dynamic proxy API URL not configured")
        provider_cls = __getattr__("ApiExtractProvider")
        return provider_cls(
            api_url=api_url,
            protocol=config.get("proxy_protocol", "http"),
            username=config.get("proxy_username", ""),
            password=config.get("proxy_password", ""),
        )

    if provider_key == "rotating_gateway":
        gateway = config.get("proxy_gateway_url", "")
        if not gateway:
            raise RuntimeError("Rotating proxy gateway address not configured")
        provider_cls = __getattr__("RotatingProxyProvider")
        return provider_cls(gateway_url=gateway)

    raise RuntimeError(f"Unknown proxy provider: {provider_key}")


def get_dynamic_proxy(extra: dict | None = None) -> Optional[str]:
    """Try to get a proxy from the configured dynamic proxy provider.

    Returns None if no dynamic proxy is configured (falls back to static proxy pool).
    """
    try:
        from infrastructure.provider_settings_repository import ProviderSettingsRepository
        repo = ProviderSettingsRepository()
        settings = repo.list_enabled("proxy")
        for setting in settings:
            if not setting.enabled:
                continue
            config = setting.get_config()
            auth = setting.get_auth()
            merged = {**config, **auth, **(extra or {})}
            try:
                provider = create_proxy_provider(setting.provider_key, merged)
                proxy = provider.get_proxy()
                if proxy:
                    return proxy
            except Exception as exc:
                logger.debug(f"[ProxyProvider] {setting.provider_key} fetch failed: {exc}")
                continue
    except Exception:
        pass
    return None
