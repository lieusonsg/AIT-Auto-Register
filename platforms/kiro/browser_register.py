"""Kiro (AWS Builder ID) browser registration flow (Camoufox).

Registration flow:
  1. Open app.kiro.dev/signin
  2. Click "AWS Builder ID" option
  3. Redirect to us-east-1.signin.aws -> profile.aws.amazon.com
  4. AWS Builder ID registration SPA:
     a. enter-email step: confirm/fill email -> Continue
     b. enter-name step: fill name -> Continue
     c. verify-email step: fill OTP -> Continue
     d. create-password step: set password -> Continue
  5. Redirect back to app.kiro.dev, extract Cognito tokens from localStorage
"""
import random
import string
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from camoufox.sync_api import Camoufox

KIRO_URL = "https://app.kiro.dev"
AWS_SIGNIN_DOMAIN = "signin.aws"
AWS_PROFILE_DOMAIN = "profile.aws.amazon.com"


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


def _wait_for_url(page, substring: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if substring in page.url:
            return True
        time.sleep(1)
    return False


def _js_click_by_text(page, *texts) -> bool:
    """Find and click the smallest leaf node with exact textContent match using JS."""
    for text in texts:
        try:
            clicked = page.evaluate(f"""
            () => {{
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null
                );
                let node;
                while (node = walker.nextNode()) {{
                    if (node.textContent.trim() === {repr(text)}) {{
                        const el = node.parentElement;
                        if (el) {{ el.click(); return true; }}
                    }}
                }}
                return false;
            }}
            """)
            if clicked:
                return True
        except Exception:
            pass
    return False


def _click_submit_button(page, timeout: int = 8) -> bool:
    """Click submit button (AWS pages use button[type=submit])."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 1. Prefer Playwright locator text exact match
        for text in ["Continue", "Next", "Verify", "Create account", "Sign in", "Submit"]:
            try:
                el = page.locator(f'text="{text}"').last
                if el.is_visible():
                    el.click()
                    return True
            except Exception:
                pass
        # 2. button[type=submit]
        try:
            el = page.query_selector('button[type="submit"]:not([disabled])')
            if el and el.is_visible():
                el.click()
                return True
        except Exception:
            pass
        # 3. JS text walker
        if _js_click_by_text(page, "Continue", "Next", "Verify", "Create account"):
            return True
        time.sleep(0.5)
    return False


def _fill_input_wait(page, selectors: list, value: str, timeout: int = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    el.fill(value)
                    return True
            except Exception:
                pass
        time.sleep(0.5)
    return False


def _get_kiro_tokens(page, timeout: int = 30) -> dict:
    """Extract Cognito accessToken / refreshToken from localStorage."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = page.evaluate("""
            () => {
                const out = {};
                for (const k of Object.keys(localStorage)) {
                    out[k] = localStorage.getItem(k);
                }
                return out;
            }
            """)
            access = refresh = id_token = ""
            for k, v in result.items():
                kl = k.lower()
                if "accesstoken" in kl and not access:
                    access = v
                if "refreshtoken" in kl and not refresh:
                    refresh = v
                if "idtoken" in kl and not id_token:
                    id_token = v
            if access:
                return {"accessToken": access, "refreshToken": refresh, "idToken": id_token}
        except Exception:
            pass
        time.sleep(2)
    return {}


def _random_name() -> str:
    first = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 7))).capitalize()
    last = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 7))).capitalize()
    return f"{first} {last}"


class KiroBrowserRegister:
    def __init__(
        self,
        *,
        headless: bool = True,
        proxy: Optional[str] = None,
        otp_callback: Optional[Callable[[], str]] = None,
        log_fn: Callable[[str], None] = print,
    ):
        self.headless = headless
        self.proxy = proxy
        self.otp_callback = otp_callback
        self.log = log_fn

    def _handle_aws_profile_spa(self, page, email: str, password: str) -> None:
        """Handle the multi-step registration SPA on profile.aws.amazon.com.

        Steps correspond to URL hash:
          #/signup/enter-email  -> fill/confirm email -> Continue
          #/signup/enter-name   -> fill name -> Continue
          #/signup/verify-email -> fill OTP -> Continue
          #/signup/create-password -> fill password -> Continue (optional)
        """
        deadline = time.time() + 300  # Wait up to 5 minutes for the entire flow

        email_selectors = [
            'input[placeholder*="username@example.com"]',
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
        ]
        name_selectors = [
            'input[placeholder*="Maria"]',
            'input[placeholder*="name" i]',
            'input[name="name"]',
            'input[name="fullName"]',
        ]
        otp_selectors = [
            'input[placeholder*="6"]',
            'input[name="otp"]',
            'input[name="code"]',
            'input[autocomplete="one-time-code"]',
            'input[inputmode="numeric"]',
            'input[maxlength="6"]',
        ]
        pwd_selectors = [
            'input[type="password"]',
            'input[name="password"]',
        ]

        handled_steps = set()
        enter_email_retries = 0
        prev_hash = None
        hash_stuck_since = None

        while time.time() < deadline:
            url = page.url
            hash_part = url.split("#")[-1] if "#" in url else ""

            # Redirected back to kiro.dev -> done
            if "kiro.dev" in url and "profile.aws" not in url and "signin.aws" not in url:
                return

            # Detect if hash is stuck (same hash for too long and already processed) -> allow retry
            if hash_part == prev_hash:
                if hash_stuck_since is None:
                    hash_stuck_since = time.time()
                elif time.time() - hash_stuck_since > 20:
                    step_key = hash_part.split("/")[-1]
                    if step_key in handled_steps:
                        self.log(f"Warning: step {step_key} stuck for 20 seconds, removing marker to retry")
                        handled_steps.discard(step_key)
                        hash_stuck_since = None
            else:
                prev_hash = hash_part
                hash_stuck_since = None

            # --- enter-email step (email + name on same page) ---
            if "enter-email" in hash_part and "enter-email" not in handled_steps:
                enter_email_retries += 1
                if enter_email_retries > 5:
                    raise RuntimeError(
                        f"AWS enter-email step retried over 5 times and still cannot proceed -- "
                        f"email domain may be rejected by AWS (url={page.url})"
                    )
                self.log(f"AWS step: confirm email + fill name (attempt #{enter_email_retries})")
                time.sleep(1.5)  # Give SPA time to render
                # Fill email (if empty)
                for sel in email_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            cur = el.input_value() or ""
                            if not cur:
                                el.fill(email)
                            break
                    except Exception:
                        pass
                # Wait for name input to appear (up to 15 seconds)
                name = _random_name()
                name_filled = False
                name_deadline = time.time() + 15
                while time.time() < name_deadline and not name_filled:
                    for sel in name_selectors:
                        try:
                            el = page.query_selector(sel)
                            if el and el.is_visible():
                                el.click()
                                time.sleep(0.2)
                                el.fill(name)
                                time.sleep(0.2)
                                # Confirm fill succeeded
                                if el.input_value():
                                    self.log(f"Filled name: {name}")
                                    name_filled = True
                                    break
                        except Exception:
                            pass
                    if not name_filled:
                        time.sleep(0.5)

                if not name_filled:
                    self.log("Warning: failed to fill name, trying JS method")
                    try:
                        page.evaluate(f"""
                        () => {{
                            const inputs = document.querySelectorAll('input[type="text"], input:not([type])');
                            for (const inp of inputs) {{
                                const ph = inp.placeholder || '';
                                if (ph.includes('Maria') || inp.closest('[class*="name"]') || 
                                    inp.closest('[class*="Name"]')) {{
                                    inp.focus();
                                    inp.value = {repr(name)};
                                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                                    return;
                                }}
                            }}
                        }}
                        """)
                        time.sleep(0.3)
                    except Exception:
                        pass

                time.sleep(0.5)
                _click_submit_button(page, timeout=8)
                handled_steps.add("enter-email")
                # Wait for hash change (up to 12 seconds), if unchanged clear marker to allow retry
                start_wait = time.time()
                while time.time() - start_wait < 12:
                    time.sleep(0.5)
                    new_url = page.url
                    new_hash = new_url.split("#")[-1] if "#" in new_url else ""
                    if new_hash != hash_part:
                        break  # Hash changed, proceed to next step
                else:
                    # Hash unchanged after 12 seconds, submission may have failed, allow retry
                    self.log("Warning: URL unchanged after enter-email submit, will retry")
                    handled_steps.discard("enter-email")
                    hash_stuck_since = time.time()
                continue

            # --- enter-name step ---
            if "enter-name" in hash_part and "enter-name" not in handled_steps:
                self.log("AWS step: fill name")
                time.sleep(1.5)
                name = _random_name()
                name_filled = False
                name_deadline = time.time() + 15
                while time.time() < name_deadline and not name_filled:
                    for sel in name_selectors:
                        try:
                            el = page.query_selector(sel)
                            if el and el.is_visible():
                                el.click()
                                time.sleep(0.2)
                                el.fill(name)
                                if el.input_value():
                                    self.log(f"Filled name: {name}")
                                    name_filled = True
                                    break
                        except Exception:
                            pass
                    if not name_filled:
                        time.sleep(0.5)
                _click_submit_button(page, timeout=5)
                handled_steps.add("enter-name")
                time.sleep(2)
                continue

            # --- verify-email step ---
            if "verify-email" in hash_part and "verify-email" not in handled_steps:
                self.log("AWS step: fill verification code")
                # Wait for OTP input to appear
                otp_el = None
                otp_deadline = time.time() + 30
                while time.time() < otp_deadline:
                    for sel in otp_selectors:
                        try:
                            el = page.query_selector(sel)
                            if el and el.is_visible():
                                otp_el = el
                                break
                        except Exception:
                            pass
                    if otp_el:
                        break
                    time.sleep(1)

                if not otp_el:
                    raise RuntimeError(f"Verification code input not found: {page.url}")

                if not self.otp_callback:
                    raise RuntimeError("Kiro registration requires email verification code but otp_callback not provided")

                code = self.otp_callback()
                if not code:
                    raise RuntimeError("Failed to get email verification code")
                self.log(f"Filled verification code: {code}")
                otp_el.click()
                for digit in str(code).strip():
                    page.keyboard.press(digit)
                    time.sleep(0.1)
                time.sleep(0.5)
                _click_submit_button(page, timeout=5)
                handled_steps.add("verify-email")
                time.sleep(2)
                continue

            # --- create-password step ---
            if "create-password" in hash_part and "create-password" not in handled_steps:
                self.log("AWS step: set password")
                time.sleep(1)
                pwd_fields = []
                for sel in pwd_selectors:
                    try:
                        els = page.query_selector_all(sel)
                        pwd_fields.extend([e for e in els if e.is_visible()])
                    except Exception:
                        pass
                if pwd_fields:
                    for f in pwd_fields:
                        try:
                            f.click()
                            f.fill(password)
                            time.sleep(0.2)
                        except Exception:
                            pass
                    time.sleep(0.5)
                    _click_submit_button(page, timeout=5)
                handled_steps.add("create-password")
                time.sleep(2)
                continue

            # No hash case: may be on an intermediate redirect page, wait
            time.sleep(1)

        raise RuntimeError(f"AWS Builder ID registration did not complete within the time limit: {page.url}")

    def run(self, email: str, password: str) -> dict:
        if not self.otp_callback:
            raise RuntimeError("Kiro registration requires email verification code but otp_callback not provided")

        if not password:
            password = (
                ''.join(random.choices(string.ascii_uppercase, k=2))
                + ''.join(random.choices(string.digits, k=3))
                + ''.join(random.choices(string.ascii_lowercase, k=5))
                + '!'
            )

        proxy = _build_proxy_config(self.proxy)
        launch_opts = {"headless": self.headless}
        if proxy:
            launch_opts["proxy"] = proxy

        with Camoufox(**launch_opts) as browser:
            page = browser.new_page()

            # 1. Open Kiro login page
            self.log("Opening Kiro login page")
            page.goto(f"{KIRO_URL}/signin", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # 2. Click AWS Builder ID option
            self.log("Selecting AWS Builder ID login method")
            builder_clicked = False
            deadline_builder = time.time() + 15
            while time.time() < deadline_builder and not builder_clicked:
                # Playwright locator text exact match
                for text in ["Builder ID", "AWS Builder ID"]:
                    try:
                        el = page.locator(f'text="{text}"').last
                        if el.is_visible():
                            el.click()
                            builder_clicked = True
                            self.log(f"Clicked {text}")
                            break
                    except Exception:
                        pass
                if not builder_clicked:
                    # JS walker fallback
                    builder_clicked = _js_click_by_text(page, "Builder ID", "AWS Builder ID")
                    if builder_clicked:
                        self.log("Clicked Builder ID (JS)")
                if not builder_clicked:
                    time.sleep(0.5)

            time.sleep(2)

            # 3. There may be a secondary "Sign in" arrow (Kiro tab UI)
            _click_submit_button(page, timeout=5)
            time.sleep(2)

            # 4. Wait to enter AWS domain
            self.log("Waiting for AWS login page...")
            if not _wait_for_url(page, AWS_SIGNIN_DOMAIN, timeout=30):
                if AWS_PROFILE_DOMAIN not in page.url:
                    raise RuntimeError(f"Did not redirect to AWS login page: {page.url}")

            time.sleep(2)

            # 5. If landed on signin.aws (existing account login page), fill email and submit first
            if AWS_SIGNIN_DOMAIN in page.url:
                self.log(f"Filling email: {email}")
                email_selectors = [
                    'input[placeholder*="username@example.com"]',
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[name="username"]',
                ]
                if not _fill_input_wait(page, email_selectors, email, timeout=15):
                    raise RuntimeError(f"Email input not found: {page.url}")
                time.sleep(0.5)
                _click_submit_button(page, timeout=8)
                time.sleep(3)

            # 6. Wait to enter profile.aws.amazon.com (new account registration flow)
            # AWS redirect may take a long time, wait up to 60 seconds
            self.log("Waiting to enter AWS registration flow...")
            deadline_profile = time.time() + 60
            while time.time() < deadline_profile:
                if AWS_PROFILE_DOMAIN in page.url:
                    break
                if "kiro.dev" in page.url:
                    break
                time.sleep(1)

            if AWS_PROFILE_DOMAIN in page.url:
                self.log("Entering AWS Builder ID registration flow...")
                self._handle_aws_profile_spa(page, email, password)
            elif "kiro.dev" in page.url:
                # Existing account logged in directly
                self.log("Existing account, logged in directly")
            elif AWS_SIGNIN_DOMAIN in page.url:
                # Still on signin.aws: may be existing account password step
                self.log("Detected password input page, filling password...")
                pwd_selectors = ['input[type="password"]', 'input[name="password"]']
                _fill_input_wait(page, pwd_selectors, password, timeout=10)
                time.sleep(0.5)
                _click_submit_button(page, timeout=5)
                time.sleep(3)
                # After password submit, wait again for profile.aws or kiro.dev
                deadline2 = time.time() + 60
                while time.time() < deadline2:
                    if AWS_PROFILE_DOMAIN in page.url:
                        self.log("After password, redirected to AWS registration flow...")
                        self._handle_aws_profile_spa(page, email, password)
                        break
                    if "kiro.dev" in page.url:
                        break
                    time.sleep(1)

            # 7. Wait to redirect back to kiro.dev
            self.log("Waiting to redirect back to Kiro...")
            if not _wait_for_url(page, "kiro.dev", timeout=60):
                raise RuntimeError(f"Kiro registration did not redirect back to app: {page.url}")

            time.sleep(3)

            # 8. Extract Cognito tokens
            self.log("Extracting Kiro access tokens...")
            tokens = _get_kiro_tokens(page, timeout=20)

            self.log(f"Registration succeeded: {email}")
            return {
                "email": email,
                "password": password,
                "accessToken": tokens.get("accessToken", ""),
                "refreshToken": tokens.get("refreshToken", ""),
                "idToken": tokens.get("idToken", ""),
                "sessionToken": "",
                "clientId": "",
                "clientSecret": "",
            }
