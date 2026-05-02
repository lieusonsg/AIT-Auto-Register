"""Rotating gateway proxy provider — fixed entry with rotating exit IPs."""
from __future__ import annotations

from typing import Optional

from core.proxy_providers import BaseProxyProvider
from providers.registry import register_provider


@register_provider("proxy", "rotating_gateway")
class RotatingProxyProvider(BaseProxyProvider):
    """Fixed-entry rotating proxy — each request is automatically assigned a different IP.

    Suitable for proxy providers that offer a fixed gateway address (e.g., BrightData, Oxylabs, IPRoyal, etc.),
    format is typically: http://user:pass@gate.provider.com:port
    Each request sent through this gateway automatically uses a different exit IP.
    """

    def __init__(self, *, gateway_url: str):
        self.gateway_url = gateway_url

    @classmethod
    def from_config(cls, config: dict) -> 'RotatingProxyProvider':
        gateway = config.get("proxy_gateway_url", "")
        if not gateway:
            raise RuntimeError("Rotating proxy gateway address not configured")
        return cls(gateway_url=gateway)

    def get_proxy(self) -> Optional[str]:
        return self.gateway_url if self.gateway_url else None
