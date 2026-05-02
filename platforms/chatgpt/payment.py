"""
Payment core logic - generate Plus/Team payment links, open browser incognito, check subscription status
"""

import json
import logging
import subprocess
import sys
from typing import Optional

from curl_cffi import requests as cffi_requests

# from ..database.models import Account  # removed: external dep

logger = logging.getLogger(__name__)

PAYMENT_CHECKOUT_URL = "https://chatgpt.com/backend-api/payments/checkout"
TEAM_CHECKOUT_BASE_URL = "https://chatgpt.com/checkout/openai_llc/"
WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
WHAM_USAGE_USER_AGENT = "codex_cli_rs/0.76.0 (Debian 13.0.0; x86_64) WindowsTerminal"


def _build_proxies(proxy: Optional[str]) -> Optional[dict]:
    if proxy:
        return {"http": proxy, "https": proxy}
    return None


_COUNTRY_CURRENCY_MAP = {
    "SG": "SGD",
    "US": "USD",
    "TR": "TRY",
    "JP": "JPY",
    "HK": "HKD",
    "GB": "GBP",
    "EU": "EUR",
    "AU": "AUD",
    "CA": "CAD",
    "IN": "INR",
    "BR": "BRL",
    "MX": "MXN",
}


def _extract_oai_did(cookies_str: str) -> Optional[str]:
    """Extract oai-device-id from cookie string"""
    for part in cookies_str.split(";"):
        part = part.strip()
        if part.startswith("oai-did="):
            return part[len("oai-did="):].strip()
    return None


def _extract_chatgpt_account_id(account) -> str:
    direct_candidates = [
        getattr(account, "chatgpt_account_id", ""),
    ]
    extra = getattr(account, "extra", {}) or {}
    if isinstance(extra, dict):
        direct_candidates.extend(
            [
                extra.get("chatgpt_account_id", ""),
                extra.get("chatgptAccountId", ""),
            ]
        )
    for candidate in direct_candidates:
        text = str(candidate or "").strip()
        if text:
            return text

    id_token = getattr(account, "id_token", "") or (extra.get("id_token") if isinstance(extra, dict) else "")
    parsed = None
    if isinstance(id_token, dict):
        parsed = id_token
    elif isinstance(id_token, str) and id_token.strip().startswith("{"):
        try:
            parsed = json.loads(id_token)
        except Exception:
            parsed = None
    if isinstance(parsed, dict):
        for key in ("chatgpt_account_id", "chatgptAccountId", "account_id"):
            value = str(parsed.get(key) or "").strip()
            if value:
                return value
    return ""


def _normalize_subscription_plan(plan: str) -> str:
    raw = str(plan or "").strip().lower()
    if not raw:
        return "free"
    if any(token in raw for token in ("team", "enterprise", "business")):
        return "team"
    if any(token in raw for token in ("plus", "pro", "premium", "paid")):
        return "plus"
    return "free"


def _subscription_status_from_me(data: dict) -> str:
    plan = data.get("plan_type") or ""
    normalized = _normalize_subscription_plan(plan)
    if normalized != "free":
        return normalized

    orgs = data.get("orgs", {}).get("data", [])
    for org in orgs:
        settings_ = org.get("settings", {})
        normalized = _normalize_subscription_plan(settings_.get("workspace_plan_type"))
        if normalized != "free":
            return normalized
    return "free"


def _subscription_status_from_usage(data: dict) -> str:
    return _normalize_subscription_plan(data.get("plan_type"))


def _fetch_usage_data(account, proxy: Optional[str] = None) -> dict:
    if not account.access_token:
        raise ValueError("Account missing access_token")

    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "User-Agent": WHAM_USAGE_USER_AGENT,
    }
    chatgpt_account_id = _extract_chatgpt_account_id(account)
    if chatgpt_account_id:
        headers["Chatgpt-Account-Id"] = chatgpt_account_id

    resp = cffi_requests.get(
        WHAM_USAGE_URL,
        headers=headers,
        proxies=_build_proxies(proxy),
        timeout=20,
        impersonate="chrome124",
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("wham/usage response format is abnormal")
    return data


def _parse_cookie_str(cookies_str: str, domain: str) -> list:
    """Parse 'key=val; key2=val2' format into Playwright cookie list"""
    cookies = []
    # Playwright requires a leading dot for some domain cookies
    if domain == "chatgpt.com":
        domain = ".chatgpt.com"

    for part in cookies_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookie_name = name.strip()

        cookie_obj = {
            "name": cookie_name,
            "value": value.strip(),
            "domain": domain,
            "path": "/",
        }

        # Chromium/Playwright: cookies prefixed with __Secure- must have secure: True flag
        if cookie_name.startswith("__Secure-"):
            cookie_obj["secure"] = True

        cookies.append(cookie_obj)
    return cookies


def _open_url_system_browser(url: str) -> bool:
    """Fallback: open system browser in incognito mode"""
    platform = sys.platform
    try:
        if platform == "win32":
            for browser, flag in [("chrome", "--incognito"), ("msedge", "--inprivate")]:
                try:
                    subprocess.Popen(f'start {browser} {flag} "{url}"', shell=True)
                    return True
                except Exception:
                    continue
        elif platform == "darwin":
            subprocess.Popen(["open", "-a", "Google Chrome", "--args", "--incognito", url])
            return True
        else:
            for binary in ["google-chrome", "chromium-browser", "chromium"]:
                try:
                    subprocess.Popen([binary, "--incognito", url])
                    return True
                except FileNotFoundError:
                    continue
    except Exception as e:
        logger.warning(f"System browser incognito open failed: {e}")
    return False


def generate_plus_link(
    account: Account,
    proxy: Optional[str] = None,
    country: str = "SG",
) -> str:
    """Generate Plus payment link (backend sends request with account cookie)"""
    if not account.access_token:
        raise ValueError("Account missing access_token")

    currency = _COUNTRY_CURRENCY_MAP.get(country, "USD")
    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "Content-Type": "application/json",
        "oai-language": "zh-CN",
    }
    if account.cookies:
        headers["cookie"] = account.cookies
        oai_did = _extract_oai_did(account.cookies)
        if oai_did:
            headers["oai-device-id"] = oai_did

    payload = {
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": country, "currency": currency},
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": "custom",
    }

    resp = cffi_requests.post(
        PAYMENT_CHECKOUT_URL,
        headers=headers,
        json=payload,
        proxies=_build_proxies(proxy),
        timeout=30,
        impersonate="chrome110",
    )
    resp.raise_for_status()
    data = resp.json()
    if "checkout_session_id" in data:
        return TEAM_CHECKOUT_BASE_URL + data["checkout_session_id"]
    raise ValueError(data.get("detail", "API did not return checkout_session_id"))


def generate_team_link(
    account: Account,
    workspace_name: str = "MyTeam",
    price_interval: str = "month",
    seat_quantity: int = 5,
    proxy: Optional[str] = None,
    country: str = "SG",
) -> str:
    """Generate Team payment link (backend sends request with account cookie)"""
    if not account.access_token:
        raise ValueError("Account missing access_token")

    currency = _COUNTRY_CURRENCY_MAP.get(country, "USD")
    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "Content-Type": "application/json",
        "oai-language": "zh-CN",
    }
    if account.cookies:
        headers["cookie"] = account.cookies
        oai_did = _extract_oai_did(account.cookies)
        if oai_did:
            headers["oai-device-id"] = oai_did

    payload = {
        "plan_name": "chatgptteamplan",
        "team_plan_data": {
            "workspace_name": workspace_name,
            "price_interval": price_interval,
            "seat_quantity": seat_quantity,
        },
        "billing_details": {"country": country, "currency": currency},
        "promo_campaign": {
            "promo_campaign_id": "team-1-month-free",
            "is_coupon_from_query_param": True,
        },
        "cancel_url": "https://chatgpt.com/#pricing",
        "checkout_ui_mode": "custom",
    }

    resp = cffi_requests.post(
        PAYMENT_CHECKOUT_URL,
        headers=headers,
        json=payload,
        proxies=_build_proxies(proxy),
        timeout=30,
        impersonate="chrome110",
    )
    resp.raise_for_status()
    data = resp.json()
    if "checkout_session_id" in data:
        return TEAM_CHECKOUT_BASE_URL + data["checkout_session_id"]
    raise ValueError(data.get("detail", "API did not return checkout_session_id"))


def open_url_incognito(url: str, cookies_str: Optional[str] = None) -> bool:
    """Open URL in Playwright incognito mode, optionally injecting cookies"""
    import threading
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed, falling back to system browser")
        return _open_url_system_browser(url)

    def _launch():
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, args=["--incognito"])
                ctx = browser.new_context()
                if cookies_str:
                    ctx.add_cookies(_parse_cookie_str(cookies_str, "chatgpt.com"))
                page = ctx.new_page()
                page.goto(url)
                # Keep window open until user closes it
                page.wait_for_timeout(300_000)  # Wait up to 5 minutes
        except Exception as e:
            logger.warning(f"Playwright incognito open failed: {e}")

    threading.Thread(target=_launch, daemon=True).start()
    return True


def check_subscription_status(account: Account, proxy: Optional[str] = None) -> str:
    """
    Check current subscription status of the account.

    Returns:
        'free' / 'plus' / 'team'
    """
    return fetch_subscription_status_details(account, proxy=proxy)["status"]


def fetch_subscription_status_details(account: Account, proxy: Optional[str] = None) -> dict:
    """Return normalized subscription status plus raw usage data when available."""
    if not account.access_token:
        raise ValueError("Account missing access_token")

    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = cffi_requests.get(
            "https://chatgpt.com/backend-api/me",
            headers=headers,
            proxies=_build_proxies(proxy),
            timeout=20,
            impersonate="chrome110",
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            usage_data = None
            try:
                usage_data = _fetch_usage_data(account, proxy=proxy)
            except Exception as usage_exc:
                logger.info("check_subscription_status usage enrichment failed: %s", usage_exc)
            return {
                "status": _subscription_status_from_me(data),
                "source": "backend-api/me",
                "me": data,
                "usage": usage_data,
            }
    except Exception as exc:
        logger.info("check_subscription_status fallback to wham/usage: %s", exc)

    data = _fetch_usage_data(account, proxy=proxy)
    return {
        "status": _subscription_status_from_usage(data),
        "source": "backend-api/wham/usage",
        "me": None,
        "usage": data,
    }
