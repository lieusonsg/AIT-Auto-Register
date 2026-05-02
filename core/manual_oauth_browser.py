"""Backward-compatible re-export layer. New code should use core.oauth_browser directly."""
from core.oauth_browser import (  # noqa: F401
    OAuthBrowser,
    OAuthBrowser as ManualOAuthBrowser,
    OAUTH_PROVIDER_LABELS,
    OAUTH_PROVIDER_HINTS,
    oauth_provider_label,
    oauth_provider_hint_text,
    oauth_provider_hint_text as browser_login_method_text,
    finalize_oauth_email,
    _build_proxy_config,
)
