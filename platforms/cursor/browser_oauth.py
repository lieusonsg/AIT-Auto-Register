"""Cursor OAuth browser flow."""
import time

from core.oauth_browser import (
    OAuthBrowser,
    browser_login_method_text,
    finalize_oauth_email,
    oauth_provider_label,
)
from platforms.cursor.switch import get_cursor_user_info


def register_with_browser_oauth(
    *,
    proxy: str | None = None,
    oauth_provider: str = "",
    email_hint: str = "",
    timeout: int = 300,
    log_fn=print,
    headless: bool = False,
    chrome_user_data_dir: str = "",
    chrome_cdp_url: str = "",
) -> dict:
    method_text = browser_login_method_text(oauth_provider)

    with OAuthBrowser(
        proxy=proxy,
        headless=headless,
        chrome_user_data_dir=chrome_user_data_dir,
        chrome_cdp_url=chrome_cdp_url,
        log_fn=log_fn,
    ) as browser:
        browser.goto("https://authenticator.cursor.sh/sign-up")
        time.sleep(2)
        if oauth_provider and not browser.try_click_provider(oauth_provider):
            browser.goto("https://authenticator.cursor.sh/")
            time.sleep(2)
            browser.try_click_provider(oauth_provider)

        if chrome_user_data_dir or chrome_cdp_url:
            browser.auto_select_google_account()
        else:
            log_fn(f"Please complete login in the browser, you can use {method_text}, waiting up to {timeout} seconds")
            if email_hint:
                log_fn(f"Please confirm the final login email is: {email_hint}")

        token = browser.wait_for_cookie_value(
            ["WorkosCursorSessionToken"],
            timeout=timeout,
            domain_substrings=("cursor.com", "cursor.sh"),
        )
        if not token:
            raise RuntimeError(f"Cursor browser login did not get Session Token within {timeout} seconds")

        user_info = get_cursor_user_info(token) or {}
        resolved_email = finalize_oauth_email(user_info.get("email", ""), email_hint, "Cursor")
        return {
            "email": resolved_email,
            "token": token,
            "user_info": user_info,
        }


# Backward-compat alias
register_with_manual_oauth = register_with_browser_oauth
