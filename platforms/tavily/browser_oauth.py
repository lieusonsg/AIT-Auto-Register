"""Tavily OAuth browser flow."""
from __future__ import annotations

import time

from core.oauth_browser import OAUTH_PROVIDER_LABELS, OAuthBrowser, finalize_oauth_email
from platforms.tavily.browser_register import (
    click_oauth_provider,
    close_marketing_dialog,
    extract_signup_url,
    verify_api_key,
    wait_for_api_key,
    wait_for_manual_oauth_completion,
)


def _finalize_api_key(page, *, timeout: int) -> str:
    close_marketing_dialog(page)
    api_key = wait_for_api_key(page, timeout=timeout)
    if not api_key:
        try:
            page.goto("https://app.tavily.com", wait_until="networkidle", timeout=30000)
            time.sleep(3)
        except Exception:
            pass
        api_key = wait_for_api_key(page, timeout=timeout)
    if not api_key:
        raise RuntimeError("Tavily API Key not found")
    if not verify_api_key(api_key):
        raise RuntimeError("Tavily API Key verification failed")
    return api_key


def register_with_browser_oauth(
    *,
    proxy: str | None = None,
    oauth_provider: str = "",
    email_hint: str = "",
    timeout: int = 300,
    log_fn=print,
    chrome_user_data_dir: str = "",
    chrome_cdp_url: str = "",
) -> dict:
    provider = (oauth_provider or "").strip().lower()
    if not chrome_user_data_dir and not chrome_cdp_url:
        raise RuntimeError("Tavily OAuth requires reusing the local browser session, please configure chrome_user_data_dir or chrome_cdp_url")

    with OAuthBrowser(
        proxy=proxy,
        headless=False,
        chrome_user_data_dir=chrome_user_data_dir,
        chrome_cdp_url=chrome_cdp_url,
        log_fn=log_fn,
    ) as browser:
        browser.goto("https://app.tavily.com/sign-in", wait_until="networkidle", timeout=30000)
        time.sleep(2)
        page = browser.active_page()
        signup_url = extract_signup_url(page.content())
        if not signup_url:
            raise RuntimeError("Tavily signup entry not found")
        log_fn("Entering Tavily signup page")
        browser.goto(signup_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        page = browser.active_page()

        provider_label = OAUTH_PROVIDER_LABELS.get(provider, provider.title()) if provider else ""
        if provider:
            log_fn(f"Switching to {provider_label} login entry")
            if not click_oauth_provider(page, provider):
                page.goto("https://app.tavily.com/sign-in", wait_until="networkidle", timeout=30000)
                time.sleep(2)
                if not click_oauth_provider(page, provider):
                    raise RuntimeError(f"{provider_label} login entry not found")

        method_text = provider_label or "email, Google, GitHub, LinkedIn, Microsoft or any other available method"
        log_fn(f"Please complete login/authorization in the browser, you can use {method_text}, waiting up to {timeout} seconds")
        if email_hint:
            log_fn(f"Please confirm the final login email is: {email_hint}")
        if not wait_for_manual_oauth_completion(page, timeout=timeout):
            raise RuntimeError(f"Tavily browser login did not complete within {timeout} seconds")

        time.sleep(3)
        api_key = _finalize_api_key(page, timeout=20)
        return {
            "email": finalize_oauth_email(email_hint, email_hint, "Tavily"),
            "password": "",
            "api_key": api_key,
        }


register_with_manual_oauth = register_with_browser_oauth
