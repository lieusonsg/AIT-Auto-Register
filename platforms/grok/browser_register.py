"""Grok (x.ai) browser registration flow (Camoufox)."""
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from camoufox.sync_api import Camoufox

ACCOUNTS_URL = "https://accounts.x.ai"
GROK_APP_URL = "https://grok.com"


def _build_proxy_config(proxy: Optional[str]) -> Optional[dict]:
    if not proxy:
        return None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return {"server": proxy}
    config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        config["username"] = parsed.username
    if parsed.password:
        config["password"] = parsed.password
    return config


def _get_cookies(page, names: list) -> dict:
    return {c["name"]: c["value"] for c in page.context.cookies() if c["name"] in names}


def _wait_for_cookies(page, names: list, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = _get_cookies(page, names)
        if all(n in found for n in names):
            return found
        time.sleep(1)
    return _get_cookies(page, names)


class GrokBrowserRegister:
    def __init__(
        self,
        *,
        headless: bool,
        proxy: Optional[str] = None,
        otp_callback: Optional[Callable[[], str]] = None,
        log_fn: Callable[[str], None] = print,
    ):
        self.headless = headless
        self.proxy = proxy
        self.otp_callback = otp_callback
        self.log = log_fn

    def run(self, email: str, password: str) -> dict:
        proxy = _build_proxy_config(self.proxy)
        launch_opts = {"headless": self.headless}
        if proxy:
            launch_opts["proxy"] = proxy

        with Camoufox(**launch_opts) as browser:
            page = browser.new_page()
            self.log("Opening Grok registration page")
            page.goto(f"{ACCOUNTS_URL}/sign-up", wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # Click "Sign up with email" if it exists
            btn_email_sel = 'button:has-text("Sign up with email")'
            if page.query_selector(btn_email_sel):
                page.click(btn_email_sel)
                time.sleep(2)

            # Step 1: fill email
            email_sel = 'input[type="email"], input[name="email"], input[name="username"]'
            page.wait_for_selector(email_sel, timeout=15000)
            page.fill(email_sel, email)

            btn_sel = 'button[type="submit"], button[data-testid="continue"]'
            if page.query_selector(btn_sel):
                page.click(btn_sel)
            time.sleep(3)

            # OTP sent to email
            try:
                page.wait_for_selector('input[name="code"], input[placeholder*="code"], input[placeholder*="Code"]', timeout=20000)
            except Exception:
                fb = ""
                for sel in ['[role="alert"]', '.error']:
                    el = page.query_selector(sel)
                    if el:
                        fb = el.inner_text()
                        break
                raise RuntimeError(f"Did not reach verification code page: {fb or page.url}")

            if not self.otp_callback:
                raise RuntimeError("Grok registration requires email verification code but no otp_callback provided")
            self.log("Waiting for Grok verification code")
            code = self.otp_callback()
            if not code:
                raise RuntimeError("Failed to get verification code")

            code_sel = 'input[name="code"], input[data-input-otp="true"]'
            if not page.query_selector(code_sel):
                code_sel = 'input[placeholder*="code"], input[placeholder*="Code"]'
            
            # The input expects 6 characters without hyphen
            clean_code = code.replace("-", "")
            try:
                page.fill(code_sel, clean_code, force=True)
            except:
                page.locator(code_sel).press_sequentially(clean_code)

            confirm_btn = 'button:has-text("Confirm email")'
            if page.query_selector(confirm_btn):
                page.click(confirm_btn, force=True)
            elif page.query_selector(btn_sel):
                page.click(btn_sel, force=True)
            time.sleep(3)

            # May need name + password
            self.log("Waiting for name/password step")
            for _ in range(15):
                if page.query_selector('input[name="given_name"], input[placeholder*="First"], input[name="password"], input[type="password"]'):
                    break
                time.sleep(1)
            else:
                self.log("Name or password input not detected, saving screenshot to /tmp/grok_debug.png")
                page.screenshot(path="/tmp/grok_debug.png")
                with open("/tmp/grok_debug.html", "w") as f:
                    f.write(page.content())

            # DEBUG SCREENSHOT
            page.screenshot(path="/tmp/grok_name_pass.png")

            if page.query_selector('input[name="given_name"], input[name="givenName"], input[placeholder*="First"]'):
                import random, string
                first = ''.join(random.choices(string.ascii_lowercase, k=5)).capitalize()
                last = ''.join(random.choices(string.ascii_lowercase, k=5)).capitalize()
                fname_sel = 'input[name="given_name"], input[name="givenName"], input[placeholder*="First"]'
                if page.query_selector(fname_sel):
                    page.fill(fname_sel, first)
                lname_sel = 'input[name="family_name"], input[name="familyName"], input[placeholder*="Last"]'
                if page.query_selector(lname_sel):
                    page.fill(lname_sel, last)
                # DO NOT CLICK YET if password is also on screen
                if not page.query_selector('input[name="password"], input[type="password"]'):
                    if page.query_selector(btn_sel):
                        page.click(btn_sel)
                    time.sleep(2)

            for _ in range(10):
                if page.query_selector('input[name="password"], input[type="password"]'):
                    break
                time.sleep(1)

            if page.query_selector('input[name="password"], input[type="password"]'):
                page.fill('input[name="password"], input[type="password"]', password)
                
                # Try to click any checkbox (like TOS)
                checkboxes = page.query_selector_all('input[type="checkbox"]')
                for cb in checkboxes:
                    try:
                        cb.click(force=True)
                    except:
                        pass
                
                submit_btn = 'button:has-text("Complete sign up"), button:has-text("Sign up"), button[type="submit"]'
                if page.query_selector(submit_btn):
                    page.click(submit_btn)
                elif page.query_selector(btn_sel):
                    page.click(btn_sel)
                time.sleep(3)

            # Wait for sso cookie
            self.log("Waiting for Grok sso cookie")
            cookies = _wait_for_cookies(page, ["sso"], timeout=60)
            sso = cookies.get("sso", "")
            if not sso:
                self.log("Failed to get sso cookie, saving screenshot to /tmp/grok_fail_final.png")
                page.screenshot(path="/tmp/grok_fail_final.png")
                with open("/tmp/grok_fail_final.html", "w") as f:
                    f.write(page.content())
                raise RuntimeError("Failed to get Grok sso cookie")
            sso_rw = _get_cookies(page, ["sso-rw"]).get("sso-rw", "")
            self.log(f"Registration successful: {email}")
            return {"email": email, "password": password, "sso": sso, "sso_rw": sso_rw}
