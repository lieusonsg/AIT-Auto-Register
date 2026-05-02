"""ChatGPT browser registration flow (Camoufox)."""
import base64
import json
import random
import re
import secrets
import time
import uuid
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from camoufox.sync_api import Camoufox

from .constants import (
    OPENAI_AUTH,
    CHATGPT_APP,
    PLATFORM_LOGIN_ENTRY,
    SENTINEL_SDK_URL,
    SENTINEL_REQ_URL,
    SENTINEL_FRAME_URL,
    SENTINEL_BASE,
    OAUTH_CONSENT_FORM_SELECTOR,
)

EMAIL_INPUT_SELECTORS = [
    'input#login-email',
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    'input[autocomplete="username"]',
    'input[autocomplete*="username"]',
    'input[inputmode="email"]',
    'input[id*="email"]',
]

PASSWORD_INPUT_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    'input[autocomplete="new-password"]',
]

EMAIL_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button[data-testid="continue-button"]',
    'button:has-text("Continue")',
    'button:has-text("continue")',
    'button:has-text("Next")',
    'button:has-text("next")',
]

PASSWORD_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button[data-testid="continue-button"]',
    'button:has-text("Continue")',
    'button:has-text("continue")',
    'button:has-text("Sign up")',
    'button:has-text("sign up")',
    'button:has-text("Create account")',
    'button:has-text("create account")',
]

OTP_INPUT_SELECTORS = [
    "input[inputmode='numeric']",
    "input[autocomplete='one-time-code']",
    "input[type='tel']",
    "input[type='number']",
    "input[name*='code' i]",
    "input[id*='code' i]",
]

SIGNUP_RECOVERY_SELECTORS = [
    'a:has-text("Sign up")',
    'button:has-text("Sign up")',
    'a:has-text("sign up")',
    'button:has-text("sign up")',
    'a:has-text("Register")',
    'button:has-text("Register")',
    'a:has-text("Create account")',
    'button:has-text("Create account")',
    'a:has-text("Create account")',
    'button:has-text("Create account")',
    'a:has-text("Sign up")',
    'button:has-text("Sign up")',
]

PASSWORDLESS_LOGIN_SELECTORS = [
    'button[name="intent"][value="passwordless_login_send_otp"]',
    'button[value="passwordless_login_send_otp"]',
    'button:has-text("one-time code")',
    'button:has-text("one time code")',
    'button:has-text("passwordless")',
    'button:has-text("one-time code")',
    'button:has-text("verification code")',
    'button:has-text("verification code")',
]


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


def _find_first_selector(page, selectors: list[str]) -> str | None:
    for sel in selectors:
        try:
            node = page.query_selector(sel)
        except Exception:
            node = None
        if node:
            return sel
    return None


def _wait_for_any_selector(page, selectors: list[str], timeout: int = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = _find_first_selector(page, selectors)
        if found:
            return found
        time.sleep(0.5)
    return None


def _click_first(page, selectors: list[str], *, timeout: int = 10) -> str | None:
    found = _wait_for_any_selector(page, selectors, timeout=timeout)
    if not found:
        return None
    try:
        page.click(found)
        return found
    except Exception:
        return None


def _is_login_password_url(url: str) -> bool:
    return bool(re.search(r"(?:auth|accounts)\.openai\.com/.*log-?in/password", str(url or ""), flags=re.I))


def _build_manual_flow_state(page_type: str, current_url: str) -> dict:
    state = _extract_flow_state(None, current_url)
    state["page_type"] = page_type
    state["current_url"] = current_url
    return state


def _get_visible_page_text(page) -> str:
    try:
        return str(page.evaluate("() => document.body?.innerText || ''") or "")
    except Exception:
        return ""


def _has_signup_registration_choice(page) -> bool:
    if not _is_login_password_url(str(page.url or "")):
        return False
    if _find_first_selector(page, SIGNUP_RECOVERY_SELECTORS):
        return True
    text = _get_visible_page_text(page)
    return bool(re.search(r"sign\s*up|register|create\s*account", text, flags=re.I))


def _click_passwordless_login_if_available(page, log, *, context: str) -> bool:
    selector = _click_first(page, PASSWORDLESS_LOGIN_SELECTORS, timeout=1)
    if selector:
        log(f"{context} selected one-time code login: {selector}")
        time.sleep(1)
        return True
    try:
        clicked = bool(
            page.evaluate(
                """
                () => {
                  const nodes = Array.from(document.querySelectorAll('button, [role="button"], a'));
                  const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                  };
                  const target = nodes.find((el) => {
                    const text = String(el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    return visible(el) && /one-time code|one time code|passwordless/i.test(text);
                  });
                  if (!target) return false;
                  target.click();
                  return true;
                }
                """
            )
        )
    except Exception:
        clicked = False
    if clicked:
        log(f"{context} selected one-time code login")
        time.sleep(1)
    return clicked


def _get_page_oauth_url(page) -> str:
    try:
        return str(
            page.evaluate(
                """
                () => {
                  const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                  };
                  const anchors = Array.from(document.querySelectorAll('a[href*="/api/oauth/authorize"]'));
                  const anchor = anchors.find((el) => visible(el));
                  return anchor ? String(anchor.href || anchor.getAttribute('href') || '') : '';
                }
                """
            )
            or ""
        ).strip()
    except Exception:
        return ""


def _oauth_url_matches_state(url: str, state: str) -> bool:
    if not url or not state:
        return False
    return f"state={state}" in url or f"state%3D{state}" in url


def _extract_auth_error_text(page) -> str:
    selectors = [
        "text=Failed to create account",
        "text=Sorry, we cannot create your account",
        "text=Please try again",
        "text=Invalid code",
        "text=Enter a valid age to continue",
        "text=doesn't look right",
        "[role='alert']",
        ".error, [class*='error'], [class*='Error']",
    ]
    for selector in selectors:
        try:
            text = str(page.locator(selector).first.text_content(timeout=350) or "").strip()
        except Exception:
            text = ""
        if text and "oai_log" not in text and "SSR_HTML" not in text:
            return text
    return ""


def _fill_input_like_user(page, selector: str, value: str) -> bool:
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=2000)
        current = str(locator.input_value() or "").strip()
        if current == str(value).strip():
            return True
        locator.click(timeout=1500)
        _browser_pause(page)
        try:
            locator.fill("")
        except Exception:
            pass
        _browser_pause(page, headed=False)
        try:
            locator.type(value, delay=random.randint(35, 85))
        except Exception:
            try:
                page.fill(selector, value)
            except Exception:
                return False
        final_value = str(locator.input_value() or "").strip()
        if final_value == str(value):
            return True
    except Exception:
        pass

    try:
        ok = page.evaluate(
            """
            ({ selector, value }) => {
              const input = document.querySelector(selector);
              if (!input) return false;
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
              if (!setter) return false;
              setter.call(input, value);
              input.dispatchEvent(new Event('input', { bubbles: true }));
              input.dispatchEvent(new Event('change', { bubbles: true }));
              return String(input.value || '') === String(value || '');
            }
            """,
            {"selector": selector, "value": value},
        )
        return bool(ok)
    except Exception:
        return False


def _submit_form_with_fallback(page, input_selector: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                (selector) => {
                  const input = document.querySelector(selector);
                  if (!input) return false;
                  const form = input.form || input.closest?.('form');
                  if (form?.requestSubmit) {
                    form.requestSubmit();
                    return true;
                  }
                  if (form?.submit) {
                    form.submit();
                    return true;
                  }
                  input.focus?.();
                  for (const type of ['keydown', 'keypress', 'keyup']) {
                    input.dispatchEvent(new KeyboardEvent(type, {
                      key: 'Enter',
                      code: 'Enter',
                      bubbles: true,
                      cancelable: true,
                    }));
                  }
                  return true;
                }
                """,
                input_selector,
            )
        )
    except Exception:
        return False


def _sync_hidden_birthday_input(page, birthdate: str, log) -> bool:
    try:
        synced = bool(
            page.evaluate(
                """
                (value) => {
                  const input = document.querySelector("input[name='birthday']");
                  if (!input) return false;
                  input.value = value;
                  input.dispatchEvent(new Event('input', { bubbles: true }));
                  input.dispatchEvent(new Event('change', { bubbles: true }));
                  return String(input.value || '') === String(value || '');
                }
                """,
                birthdate,
            )
        )
    except Exception:
        synced = False
    if synced:
        log(f"about_you synced hidden birthday: {birthdate}")
    return synced


def _collect_visible_text_inputs(page) -> list[dict]:
    try:
        inputs = page.evaluate(
            """
            () => {
              const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
              const nodes = Array.from(document.querySelectorAll("input:not([type='hidden']):not([disabled]):not([readonly])"));
              const visible = nodes.filter((el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style
                  && style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && rect.width > 0
                  && rect.height > 0;
              });
              return visible.map((el, visibleIndex) => {
                const explicitLabels = Array.from(document.querySelectorAll('label'))
                  .filter((label) => String(label.getAttribute('for') || '') === String(el.id || ''))
                  .map((label) => normalize(label.textContent));
                const wrappedLabel = normalize(el.closest('label')?.textContent || '');
                const ariaLabel = normalize(el.getAttribute('aria-label'));
                const labelledByText = normalize(
                  String(el.getAttribute('aria-labelledby') || '')
                    .split(/\\s+/)
                    .filter(Boolean)
                    .map((id) => normalize(document.getElementById(id)?.textContent || ''))
                    .join(' ')
                );
                const parentText = normalize(el.parentElement?.textContent || '');
                return {
                  visibleIndex,
                  type: normalize(el.getAttribute('type') || el.type || ''),
                  name: normalize(el.getAttribute('name') || ''),
                  id: normalize(el.id || ''),
                  placeholder: normalize(el.getAttribute('placeholder') || ''),
                  ariaLabel,
                  labels: explicitLabels.filter(Boolean),
                  wrappedLabel,
                  labelledByText,
                  parentText,
                };
              });
            }
            """
        ) or []
    except Exception:
        inputs = []
    return [item for item in inputs if isinstance(item, dict)]


def _about_you_input_hints(entry: dict) -> str:
    parts: list[str] = []
    labels = entry.get("labels") or []
    if isinstance(labels, list):
        parts.extend(str(item or "") for item in labels)
    parts.extend(
        [
            str(entry.get("wrappedLabel") or ""),
            str(entry.get("labelledByText") or ""),
            str(entry.get("ariaLabel") or ""),
            str(entry.get("placeholder") or ""),
            str(entry.get("name") or ""),
            str(entry.get("id") or ""),
            str(entry.get("parentText") or ""),
        ]
    )
    return " ".join(part for part in parts if part).strip().lower()


def _pick_best_about_you_input(entries: list[dict], field: str, exclude_visible_indices: set[int] | None = None) -> dict | None:
    exclude = {int(value) for value in (exclude_visible_indices or set())}
    best_entry = None
    best_score = float("-inf")
    for entry in entries:
        try:
            visible_index = int(entry.get("visibleIndex"))
        except Exception:
            continue
        if visible_index in exclude:
            continue
        hints = _about_you_input_hints(entry)
        if not hints:
            continue

        score = 0
        if field == "name":
            if any(token in hints for token in ("full name", "fullname", "full name", "name")):
                score += 10
            if any(token in hints for token in (" name ", "name", "autocomplete=name")):
                score += 3
            if any(token in hints for token in ("age", "age", "birthday", "birth", "date of birth", "date of birth", "birthday")):
                score -= 8
        elif field == "age":
            if any(token in hints for token in ("age", "age", "how old")):
                score += 10
            if any(token in hints for token in ("full name", "fullname", "full name", "name")):
                score -= 10
            if "name" in hints and "age" not in hints and "age" not in hints:
                score -= 6
            if any(token in hints for token in ("birthday", "birth", "date of birth", "date of birth", "birthday")):
                score -= 3
        else:
            continue

        if score > best_score:
            best_score = score
            best_entry = entry

    if best_score > 0:
        return best_entry

    if field == "age" and len(entries) == 2:
        ordered = []
        for entry in entries:
            try:
                visible_index = int(entry.get("visibleIndex"))
            except Exception:
                continue
            if visible_index not in exclude:
                ordered.append(entry)
        if len(ordered) == 1:
            return ordered[0]
        if len(ordered) == 2:
            return ordered[1]
    return None


def _derive_registration_state_from_page(page) -> dict:
    current_url = str(page.url or "")
    state = _extract_flow_state(None, current_url)
    if state.get("page_type"):
        return state

    if _find_first_selector(page, PASSWORD_INPUT_SELECTORS):
        page_type = "login_password" if _is_login_password_url(current_url) else "create_account_password"
        return _build_manual_flow_state(page_type, current_url)

    otp_selector = _find_first_selector(page, OTP_INPUT_SELECTORS)
    if otp_selector and "password" not in otp_selector:
        return _build_manual_flow_state("email_otp_verification", current_url)

    try:
        about_visible = bool(
            page.evaluate(
                """
                () => {
                  const inputs = Array.from(document.querySelectorAll("input:not([type='hidden'])"));
                  const text = String(document.body?.innerText || '').toLowerCase();
                  const hasName = inputs.some((el) => {
                    const hint = `${el.name || ''} ${el.id || ''} ${el.placeholder || ''}`.toLowerCase();
                    return hint.includes('name');
                  });
                  const hasAgeOrBirth = inputs.some((el) => {
                    const hint = `${el.name || ''} ${el.id || ''} ${el.placeholder || ''}`.toLowerCase();
                    return hint.includes('age') || hint.includes('birth') || hint.includes('birthday');
                  });
                  return (hasName && hasAgeOrBirth) || text.includes('about you');
                }
                """
            )
        )
    except Exception:
        about_visible = False
    if about_visible:
        return _build_manual_flow_state("about_you", current_url)

    return state


def _recover_signup_password_page(page, log) -> bool:
    if not _is_login_password_url(str(page.url or "")):
        return False
    if not _has_signup_registration_choice(page):
        return False
    selector = _click_first(page, SIGNUP_RECOVERY_SELECTORS, timeout=2)
    if not selector:
        return False
    log(f"Password page fell into login state, trying to click signup entry to recover: {selector}")
    time.sleep(1.2)
    return True


def _wait_for_signup_entry_transition(page, log, timeout: int = 20) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _click_passwordless_login_if_available(page, log, context="after_email_page_submit"):
            time.sleep(0.5)
            continue
        state = _derive_registration_state_from_page(page)
        if state.get("page_type") in {
            "create_account_password",
            "login_password",
            "email_otp_verification",
            "about_you",
            "add_phone",
            "chatgpt_home",
            "oauth_callback",
        }:
            if state.get("page_type") == "login_password" and _recover_signup_password_page(page, log):
                return _derive_registration_state_from_page(page)
            return state
        error_text = _extract_auth_error_text(page)
        if error_text:
            raise RuntimeError(f"Email page submit failed: {error_text[:300]}")
        time.sleep(0.25)
    raise RuntimeError("Email page submit did not reach password/OTP page")


def _start_browser_signup_via_page(page, email: str, log) -> dict:
    for entry_url in (PLATFORM_LOGIN_ENTRY, f"{OPENAI_AUTH}/log-in"):
        try:
            log(f"Opening OpenAI signup entry: {entry_url}")
            page.goto(entry_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            log(f"Signup entry access failed: {entry_url} -> {exc}")
            continue

        initial_state = _derive_registration_state_from_page(page)
        if initial_state.get("page_type") in {
            "create_account_password",
            "login_password",
            "email_otp_verification",
            "about_you",
            "add_phone",
        }:
            return initial_state

        email_selector = _wait_for_any_selector(page, EMAIL_INPUT_SELECTORS, timeout=12)
        if not email_selector:
            continue
        if not _fill_input_like_user(page, email_selector, email):
            raise RuntimeError("Email page fill failed")
        log(f"Email page input: {email_selector}")

        inline_state = _derive_registration_state_from_page(page)
        if inline_state.get("page_type") in {"create_account_password", "login_password"}:
            if inline_state.get("page_type") == "login_password" and _recover_signup_password_page(page, log):
                return _derive_registration_state_from_page(page)
            return inline_state

        submit_selector = _click_first(page, EMAIL_SUBMIT_SELECTORS, timeout=8)
        if submit_selector:
            log(f"Email page clicked continue button: {submit_selector}")
        elif _submit_form_with_fallback(page, email_selector):
            log("Email page no clickable Continue found, used form fallback submit")
        else:
            raise RuntimeError("Email page Continue button not found")

        return _wait_for_signup_entry_transition(page, log)

    raise RuntimeError("OpenAI signup entry email input not found")


def _start_browser_signup_via_authorize(page, email: str, device_id: str, log) -> dict:
    log("Visiting ChatGPT homepage...")
    page.goto(f"{CHATGPT_APP}/", wait_until="domcontentloaded", timeout=30000)

    log("Getting CSRF token...")
    csrf_token = _get_browser_csrf_token(page)
    if not csrf_token:
        raise RuntimeError("Failed to get CSRF token")

    log(f"Submitting email: {email}")
    authorize_url = _start_browser_signin(page, email, device_id, csrf_token)
    if not authorize_url:
        raise RuntimeError("Email submit failed, no authorize URL obtained")

    final_url = _browser_authorize(page, authorize_url, log)
    if not final_url:
        raise RuntimeError("Failed to access authorize URL")
    return _derive_registration_state_from_page(page)


def _dump_debug(page, prefix: str) -> None:
    page.screenshot(path=f"/tmp/{prefix}.png")
    with open(f"/tmp/{prefix}.html", "w") as f:
        f.write(page.content())


def _get_cookies(page) -> dict:
    return {c["name"]: c["value"] for c in page.context.cookies()}


def _random_chrome_ua() -> str:
    patch = random.randint(0, 220)
    return (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/136.0.7103.{patch} Safari/537.36"
    )


def _infer_sec_ch_ua(user_agent: str) -> str:
    match = re.search(r"Chrome/(\d+)", str(user_agent or ""))
    major = str(match.group(1) if match else "136")
    return f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not.A/Brand";v="99"'


def _build_browser_headers(
    *,
    user_agent: str,
    accept: str,
    referer: str = "",
    origin: str = "",
    content_type: str = "",
    navigation: bool = False,
    extra_headers: dict | None = None,
) -> dict:
    headers = {
        "user-agent": user_agent or _random_chrome_ua(),
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": _infer_sec_ch_ua(user_agent),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "accept": accept,
    }
    if referer:
        headers["referer"] = referer
    if origin:
        headers["origin"] = origin
    if content_type:
        headers["content-type"] = content_type
    if navigation:
        headers["sec-fetch-dest"] = "document"
        headers["sec-fetch-mode"] = "navigate"
        headers["sec-fetch-user"] = "?1"
        headers["upgrade-insecure-requests"] = "1"
    else:
        headers["sec-fetch-dest"] = "empty"
        headers["sec-fetch-mode"] = "cors"
    for key, value in dict(extra_headers or {}).items():
        if value is not None:
            headers[key] = value
    return headers


def _browser_pause(page, *, headed: bool = True):
    delay_ms = random.randint(150, 450) if headed else random.randint(60, 180)
    try:
        page.wait_for_timeout(delay_ms)
    except Exception:
        time.sleep(delay_ms / 1000)


def _generate_datadog_trace_headers() -> dict:
    trace_hex = secrets.token_hex(8).rjust(16, "0")
    parent_hex = secrets.token_hex(8).rjust(16, "0")
    trace_id = str(int(trace_hex, 16))
    parent_id = str(int(parent_hex, 16))
    return {
        "traceparent": f"00-0000000000000000{trace_hex}-{parent_hex}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": trace_id,
    }


def _infer_page_type(data: dict | None, current_url: str = "") -> str:
    raw = data if isinstance(data, dict) else {}
    page_type = str(((raw.get("page") or {}).get("type")) or "").strip().lower().replace("-", "_").replace("/", "_").replace(" ", "_")
    if page_type:
        return page_type
    url = (current_url or "").lower()
    if "code=" in url:
        return "oauth_callback"
    if "create-account/password" in url:
        return "create_account_password"
    if "email-verification" in url or "email-otp" in url:
        return "email_otp_verification"
    if "about-you" in url:
        return "about_you"
    if "log-in/password" in url:
        return "login_password"
    if "sign-in-with-chatgpt" in url and "consent" in url:
        return "consent"
    if "workspace" in url and "select" in url:
        return "workspace_selection"
    if "organization" in url and "select" in url:
        return "organization_selection"
    if "add-phone" in url:
        return "add_phone"
    if "/api/oauth/oauth2/auth" in url:
        return "external_url"
    if "chatgpt.com" in url:
        return "chatgpt_home"
    return ""


def _extract_flow_state(data: dict | None, current_url: str = "") -> dict:
    raw = data if isinstance(data, dict) else {}
    page = raw.get("page") or {}
    payload = page.get("payload") or {}
    continue_url = str(raw.get("continue_url") or payload.get("url") or "").strip()
    if continue_url and continue_url.startswith("/"):
        continue_url = urljoin(OPENAI_AUTH, continue_url)
    effective_url = continue_url or current_url
    return {
        "page_type": _infer_page_type(raw, effective_url),
        "continue_url": continue_url,
        "method": str(raw.get("method") or payload.get("method") or "GET").upper(),
        "current_url": effective_url,
        "payload": payload if isinstance(payload, dict) else {},
        "raw": raw,
    }


def _extract_code_from_url(url: str) -> str:
    if not url or "code=" not in url:
        return ""
    try:
        from urllib.parse import parse_qs, urlparse as _up

        parsed = _up(url)
        values = parse_qs(parsed.query, keep_blank_values=True)
        return str((values.get("code") or [""])[0] or "").strip()
    except Exception:
        return ""


def _normalize_url(target_url: str, base_url: str = OPENAI_AUTH) -> str:
    value = str(target_url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    try:
        return urljoin(base_url, value)
    except Exception:
        return value


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        pad = "=" * ((4 - (len(payload) % 4)) % 4)
        return json.loads(base64.urlsafe_b64decode((payload + pad).encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


class _SentinelTokenGenerator:
    def __init__(self, device_id: str, user_agent: str):
        self.device_id = device_id or str(uuid.uuid4())
        self.user_agent = user_agent or _random_chrome_ua()
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a32(text: str) -> str:
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        h ^= (h >> 16)
        h = (h * 2246822507) & 0xFFFFFFFF
        h ^= (h >> 13)
        h = (h * 3266489909) & 0xFFFFFFFF
        h ^= (h >> 16)
        return f"{h & 0xFFFFFFFF:08x}"

    @staticmethod
    def _b64(data) -> str:
        return base64.b64encode(json.dumps(data, separators=(",", ":")).encode("utf-8")).decode("ascii")

    def _config(self) -> list:
        perf_now = 1000 + random.random() * 49000
        return [
            "1920x1080",
            time.strftime("%a, %d %b %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime()),
            4294705152,
            random.random(),
            self.user_agent,
            SENTINEL_SDK_URL,
            None,
            None,
            "en-US",
            "en-US,en",
            random.random(),
            "webkitTemporaryStorage−undefined",
            "location",
            "Object",
            perf_now,
            self.sid,
            "",
            random.choice([4, 8, 12, 16]),
            int(time.time() * 1000 - perf_now),
        ]

    def generate_requirements_token(self) -> str:
        cfg = self._config()
        cfg[3] = 1
        cfg[9] = round(5 + random.random() * 45)
        return "gAAAAAC" + self._b64(cfg)

    def generate_token(self, seed: str, difficulty: str) -> str:
        max_attempts = 500000
        cfg = self._config()
        start_ms = int(time.time() * 1000)
        diff = str(difficulty or "0")
        for nonce in range(max_attempts):
            cfg[3] = nonce
            cfg[9] = round(int(time.time() * 1000) - start_ms)
            encoded = self._b64(cfg)
            digest = self._fnv1a32((seed or "") + encoded)
            if digest[: len(diff)] <= diff:
                return "gAAAAAB" + encoded + "~S"
        return "gAAAAAB" + self._b64(None)


def _browser_fetch(page, url: str, *, method: str = "GET", headers: dict | None = None, body: str | None = None, redirect: str = "manual", timeout_ms: int = 30000) -> dict:
    return page.evaluate(
        """
        async ({ url, method, headers, body, redirect, timeoutMs }) => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(new Error(`fetch timeout after ${timeoutMs}ms`)), timeoutMs);
          try {
            const resp = await fetch(url, {
              method,
              headers: headers || {},
              body: body === null ? undefined : body,
              redirect,
              signal: controller.signal,
            });
            const respHeaders = {};
            resp.headers.forEach((v, k) => { respHeaders[k] = v; });
            let text = '';
            try { text = await resp.text(); } catch {}
            let data = null;
            try { data = JSON.parse(text); } catch {}
            return { ok: resp.ok, status: resp.status, url: resp.url || url, headers: respHeaders, text, data };
          } catch (e) {
            return { ok: false, status: 0, url, headers: {}, text: String(e && e.message || e), data: null };
          } finally {
            clearTimeout(timer);
          }
        }
        """,
        {
            "url": url,
            "method": method,
            "headers": headers or {},
            "body": body,
            "redirect": redirect,
            "timeoutMs": timeout_ms,
        },
    )


def _build_browser_sentinel_token(page, device_id: str, flow: str, user_agent: str) -> str:
    generator = _SentinelTokenGenerator(device_id, user_agent)
    req_body = json.dumps(
        {"p": generator.generate_requirements_token(), "id": device_id, "flow": flow},
        separators=(",", ":"),
    )
    result = _browser_fetch(
        page,
        SENTINEL_REQ_URL,
        method="POST",
        headers=_build_browser_headers(
            user_agent=user_agent,
            accept="*/*",
            referer=SENTINEL_FRAME_URL,
            origin=SENTINEL_BASE,
            content_type="text/plain;charset=UTF-8",
            extra_headers={
                "sec-fetch-site": "same-origin",
            },
        ),
        body=req_body,
        redirect="follow",
    )
    data = result.get("data") or {}
    challenge_token = str(data.get("token") or "").strip()
    if not challenge_token:
        return ""
    pow_meta = data.get("proofofwork") or {}
    if pow_meta.get("required") and pow_meta.get("seed"):
        p_value = generator.generate_token(str(pow_meta.get("seed") or ""), str(pow_meta.get("difficulty") or "0"))
    else:
        p_value = generator.generate_requirements_token()
    return json.dumps(
        {
            "p": p_value,
            "t": "",
            "c": challenge_token,
            "id": device_id,
            "flow": flow,
        },
        separators=(",", ":"),
    )


def _submit_browser_user_register(page, email: str, password: str, device_id: str, user_agent: str) -> dict:
    headers = _build_browser_headers(
        user_agent=user_agent,
        accept="application/json",
        referer=f"{OPENAI_AUTH}/create-account/password",
        origin=OPENAI_AUTH,
        content_type="application/json",
        extra_headers={
            "sec-fetch-site": "same-origin",
            "oai-device-id": device_id,
            **_generate_datadog_trace_headers(),
        },
    )
    sentinel = _build_browser_sentinel_token(page, device_id, "username_password_create", user_agent)
    if sentinel:
        headers["openai-sentinel-token"] = sentinel
    _browser_pause(page)
    return _browser_fetch(
        page,
        f"{OPENAI_AUTH}/api/accounts/user/register",
        method="POST",
        headers=headers,
        body=json.dumps({"username": email, "password": password}),
        redirect="follow",
    )


def _send_browser_email_otp(page) -> dict:
    _browser_pause(page)
    return _browser_fetch(
        page,
        f"{OPENAI_AUTH}/api/accounts/email-otp/send",
        method="GET",
        headers={
            "accept": "application/json, text/plain, */*",
            "referer": f"{OPENAI_AUTH}/create-account/password",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "accept-language": "en-US,en;q=0.9",
        },
        redirect="follow",
    )


def _decode_oauth_session_cookie(cookies_dict: dict) -> dict:
    raw = str(cookies_dict.get("oai-client-auth-session") or "").strip()
    if not raw:
        return {}
    first = raw.split(".")[0]
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            pad = "=" * ((4 - (len(first) % 4)) % 4)
            decoded = decoder((first + pad).encode("ascii")).decode("utf-8")
            parsed = json.loads(decoded)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return {}


def _extract_workspace_from_consent_html(session, consent_url: str) -> dict:
    try:
        response = session.get(consent_url, allow_redirects=True, timeout=30)
        html = response.text or ""
        if "workspaces" not in html:
            return {}
        ids = re.findall(r'"id"(?:,|:)"([0-9a-f-]{36})"', html, flags=re.I)
        kinds = re.findall(r'"kind"(?:,|:)"([^"]+)"', html, flags=re.I)
        if not ids:
            return {}
        seen: set[str] = set()
        workspaces: list[dict] = []
        for idx, workspace_id in enumerate(ids):
            if workspace_id in seen:
                continue
            seen.add(workspace_id)
            item = {"id": workspace_id}
            if idx < len(kinds):
                item["kind"] = kinds[idx]
            workspaces.append(item)
        return {"workspaces": workspaces} if workspaces else {}
    except Exception:
        return {}


def _seed_session_cookies(session, cookies_dict: dict):
    for name, value in cookies_dict.items():
        for domain in [".openai.com", ".chatgpt.com", ".auth.openai.com", "auth.openai.com", "chatgpt.com"]:
            try:
                session.cookies.set(name, value, domain=domain, path="/")
            except Exception:
                pass


def _follow_redirects_for_code(session, start_url: str, log, *, max_redirects: int = 12) -> str:
    current_url = start_url
    for idx in range(max_redirects):
        response = session.get(current_url, allow_redirects=False, timeout=30)
        log(f"  redirect-follow[{idx+1}] {response.status_code} {str(current_url)[:140]}")
        location = str(response.headers.get("Location") or "").strip()
        if not location:
            break
        next_url = urljoin(current_url, location)
        code = _extract_code_from_url(next_url)
        if code:
            return next_url
        if response.status_code not in (301, 302, 303, 307, 308):
            break
        current_url = next_url
    return ""


def _complete_oauth_with_session(cookies_dict: dict, oauth_start, proxy: str | None, log) -> dict | None:
    from .oauth import submit_callback_url
    from curl_cffi import requests as cffi_requests

    s = cffi_requests.Session(impersonate="chrome131")
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    _seed_session_cookies(s, cookies_dict)

    try:
        session_meta = _decode_oauth_session_cookie(cookies_dict)
        consent_url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
        workspaces = list(session_meta.get("workspaces") or [])
        if not workspaces:
            session_meta = _extract_workspace_from_consent_html(s, consent_url)
            workspaces = list(session_meta.get("workspaces") or [])
        if not workspaces:
            log("  Warning: missing oai-client-auth-session workspaces, OAuth failed")
            return None
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        log(f"  Selected workspace: {workspace_id}")
        ws_resp = s.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={
                "accept": "application/json",
                "referer": consent_url,
                "origin": OPENAI_AUTH,
                "content-type": "application/json",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            },
            data=json.dumps({"workspace_id": workspace_id}),
            allow_redirects=False,
            timeout=30,
        )
        log(f"  workspace/select -> {ws_resp.status_code}")

        next_url = str(ws_resp.headers.get("Location") or "").strip()
        next_data = {}
        if not next_url:
            try:
                next_data = ws_resp.json() or {}
            except Exception:
                next_data = {}
            next_url = str(next_data.get("continue_url") or "").strip()
        next_url = _normalize_url(next_url, consent_url)
        direct_code = _extract_code_from_url(next_url)
        if direct_code:
            result_json = submit_callback_url(
                callback_url=next_url,
                expected_state=oauth_start.state,
                code_verifier=oauth_start.code_verifier,
                proxy_url=proxy,
            )
            return json.loads(result_json)

        orgs = list((((next_data.get("data") or {}).get("orgs")) or []))
        if orgs and orgs[0].get("id"):
            org_id = str(orgs[0].get("id") or "").strip()
            org_body = {"org_id": org_id}
            projects = list(orgs[0].get("projects") or [])
            if projects and projects[0].get("id"):
                org_body["project_id"] = str(projects[0].get("id") or "").strip()
            log(f"  Selected organization: {org_id}")
            org_resp = s.post(
                "https://auth.openai.com/api/accounts/organization/select",
                headers={
                    "accept": "application/json",
                    "referer": consent_url,
                    "origin": OPENAI_AUTH,
                    "content-type": "application/json",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                },
                data=json.dumps(org_body),
                allow_redirects=False,
                timeout=30,
            )
            log(f"  organization/select -> {org_resp.status_code}")
            next_url = str(org_resp.headers.get("Location") or "").strip() or next_url
            if not next_url:
                try:
                    org_data = org_resp.json() or {}
                    next_url = str(org_data.get("continue_url") or "").strip()
                    if not next_url:
                        org_state = _extract_flow_state(org_data, str(org_resp.url))
                        next_url = org_state.get("continue_url") or org_state.get("current_url") or ""
                except Exception:
                    next_url = ""
            next_url = _normalize_url(next_url, consent_url)

        if not next_url and next_data:
            state = _extract_flow_state(next_data, str(ws_resp.url))
            next_url = state.get("continue_url") or state.get("current_url") or ""
            next_url = _normalize_url(next_url, consent_url)

        if not next_url:
            next_url = "https://auth.openai.com/api/oauth/oauth2/auth?" + oauth_start.auth_url.split("?", 1)[1]

        callback_url = _follow_redirects_for_code(s, next_url, log)
        if not callback_url:
            log("  Warning: failed to follow redirects to OAuth callback")
            return None
        result_json = submit_callback_url(
            callback_url=callback_url,
            expected_state=oauth_start.state,
            code_verifier=oauth_start.code_verifier,
            proxy_url=proxy,
        )
        return json.loads(result_json)
    except Exception as e:
        log(f"  OAuth session completion exception: {e}")
        return None


def _submit_callback_result(callback_url: str, oauth_start, proxy: str | None) -> dict:
    from .oauth import submit_callback_url

    result_json = submit_callback_url(
        callback_url=callback_url,
        expected_state=oauth_start.state,
        code_verifier=oauth_start.code_verifier,
        proxy_url=proxy,
    )
    return json.loads(result_json)


def _extract_callback_url_from_exception(exc: Exception) -> str:
    text = str(exc or "")
    if not text:
        return ""
    match = re.search(r"(https?://localhost[^\s\"')]+)", text, flags=re.I)
    if not match:
        return ""
    callback_url = str(match.group(1) or "").strip().rstrip(".,")
    return callback_url if _extract_code_from_url(callback_url) else ""


def _derive_oauth_state_from_page(page) -> dict:
    state = _derive_registration_state_from_page(page)
    if state.get("page_type"):
        return state
    current_url = str(page.url or "")
    if _find_first_selector(page, EMAIL_INPUT_SELECTORS):
        return _build_manual_flow_state("login_email", current_url)
    return _extract_flow_state(None, current_url)


def _submit_login_email_via_page(page, email: str, log) -> dict:
    input_selector = _wait_for_any_selector(page, EMAIL_INPUT_SELECTORS, timeout=15)
    if not input_selector:
        raise RuntimeError("OAuth email page input not found")
    if not _fill_input_like_user(page, input_selector, email):
        raise RuntimeError("OAuth email page fill failed")
    log(f"OAuth email page input: {input_selector}")
    _browser_pause(page)

    start_url = str(page.url or "")
    submit_selector = _click_first(page, EMAIL_SUBMIT_SELECTORS, timeout=8)
    if submit_selector:
        log(f"OAuth email page clicked continue button: {submit_selector}")
    elif _submit_form_with_fallback(page, input_selector):
        log("OAuth email page no clickable Continue found, used form fallback submit")
    else:
        raise RuntimeError("OAuth email page Continue button not found")

    deadline = time.time() + 20
    last_url = start_url
    while time.time() < deadline:
        current_url = str(page.url or "")
        last_url = current_url or last_url
        if _click_passwordless_login_if_available(page, log, context="after_OAuth_email_submit"):
            time.sleep(0.5)
            continue
        state = _derive_oauth_state_from_page(page)
        page_type = str(state.get("page_type") or "")
        if page_type in {
            "login_password",
            "create_account_password",
            "email_otp_verification",
            "about_you",
            "consent",
            "workspace_selection",
            "organization_selection",
            "add_phone",
            "external_url",
            "oauth_callback",
            "chatgpt_home",
        }:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        if current_url != start_url and page_type != "login_email":
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        error_text = _extract_auth_error_text(page)
        if error_text:
            return {"ok": False, "status": 400, "url": current_url, "data": None, "text": error_text}
        time.sleep(0.5)
    return {"ok": False, "status": 0, "url": last_url, "data": None, "text": "OAuth email page submit did not redirect"}


def _do_codex_oauth(page, cookies_dict: dict, email: str, password: str, otp_callback, phone_callback, proxy: str | None, log) -> dict | None:
    """Complete Codex OAuth within a real browser session, returns full token package."""
    from .oauth import generate_oauth_url
    from .constants import CODEX_CLIENT_ID, CODEX_REDIRECT_URI, CODEX_SCOPE

    oauth_start = generate_oauth_url(
        redirect_uri=CODEX_REDIRECT_URI,
        scope=CODEX_SCOPE,
        client_id=CODEX_CLIENT_ID,
    )
    try:
        user_agent = str(page.evaluate("() => navigator.userAgent") or "").strip() or _random_chrome_ua()
    except Exception:
        user_agent = _random_chrome_ua()
    device_id = str(cookies_dict.get("oai-did") or uuid.uuid4())
    log(f"  OAuth state={oauth_start.state[:20]}...")

    try:
        try:
            page.goto(oauth_start.auth_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            callback_url = _extract_callback_url_from_exception(exc)
            if callback_url:
                log(f"  OAuth bootstrap directly captured callback: {callback_url[:100]}...")
                return _submit_callback_result(callback_url, oauth_start, proxy)
            raise

        current_url = str(page.url or "")
        log(f"  OAuth bootstrap -> {current_url[:100]}...")

        for step in range(20):
            state = _derive_oauth_state_from_page(page)
            current_url = str(page.url or "")
            next_url = str(state.get("continue_url") or "").strip()
            log(
                f"  OAuth state step[{step+1}/20]: "
                f"page={state.get('page_type') or '-'} next={next_url[:60]}"
                f" url={current_url[:120]}"
            )

            callback_url = ""
            if _extract_code_from_url(current_url):
                callback_url = current_url
            elif _extract_code_from_url(next_url):
                callback_url = next_url
            if callback_url:
                return _submit_callback_result(callback_url, oauth_start, proxy)

            page_oauth_url = _get_page_oauth_url(page)
            if (
                page_oauth_url
                and page_oauth_url != current_url
                and _oauth_url_matches_state(page_oauth_url, oauth_start.state)
            ):
                log("  OAuth page detected updated authorization link, following page authorization link...")
                page.goto(page_oauth_url, wait_until="domcontentloaded", timeout=30000)
                continue

            if state["page_type"] == "login_email":
                log("  OAuth page requires email login, submitting email...")
                email_resp = _submit_login_email_via_page(page, email, log)
                log(f"  OAuth email page submit status: {email_resp.get('status', 0)}")
                if not email_resp.get("ok"):
                    raise RuntimeError(f"OAuth email page submit failed: {(email_resp.get('text') or '')[:300]}")
                continue

            if state["page_type"] in {"login_password", "create_account_password"}:
                log("  OAuth page requires password login, submitting password...")
                # In OAuth flow, directly fill password for login, do not attempt to recover to signup state
                password_resp = _submit_oauth_password_direct(page, password, log)
                log(f"  OAuth password page submit status: {password_resp.get('status', 0)}")
                if not password_resp.get("ok"):
                    raise RuntimeError(f"OAuth password page submit failed: {(password_resp.get('text') or '')[:300]}")
                continue

            if state["page_type"] == "email_otp_verification":
                if not otp_callback:
                    log("  Warning: OAuth requires email OTP but no otp_callback provided")
                    return None
                log("  OAuth waiting for email verification code...")
                code = otp_callback()
                if not code:
                    log("  Warning: OAuth OTP retrieval failed")
                    return None
                otp_resp = _submit_otp_via_page(page, code, log)
                log(f"  OAuth OTP page submit status: {otp_resp.get('status', 0)}")
                if not otp_resp.get("ok"):
                    raise RuntimeError(f"OAuth OTP verification failed: {(otp_resp.get('text') or '')[:300]}")
                continue

            if state["page_type"] == "about_you":
                log("  OAuth page showing about_you, continuing page fill...")
                about_resp = _submit_about_you_via_page(page, log)
                log(f"  OAuth about_you submit status: {about_resp.get('status', 0)}")
                if not about_resp.get("ok"):
                    raise RuntimeError(f"OAuth about_you submit failed: {(about_resp.get('text') or '')[:300]}")
                continue

            if state["page_type"] in {"consent", "workspace_selection", "organization_selection", "external_url"}:
                browser_result = _complete_oauth_in_browser(page, oauth_start, proxy, log)
                if browser_result:
                    return browser_result
                cookies_dict = _get_cookies(page)
                session_result = _complete_oauth_with_session(cookies_dict, oauth_start, proxy, log)
                if session_result:
                    return session_result
                log("  Warning: page reached consent/workspace, but session completion failed")
                return None

            if state["page_type"] == "add_phone":
                if phone_callback:
                    log("  OAuth detected add_phone, executing SMS verification first...")
                    try:
                        _handle_add_phone_challenge(
                            page, phone_callback,
                            device_id=device_id, user_agent=user_agent,
                            log=log, resume_url=oauth_start.auth_url,
                        )
                        continue
                    except Exception as exc:
                        log(f"  SMS verification failed, stopping OAuth flow: {exc}")
                        return None

                # First try to skip add_phone, directly re-visit OAuth authorization URL
                # User is already logged in, re-visiting auth URL should directly jump to callback
                log("  Detected add_phone, trying to skip...")
                try:
                    page.goto(oauth_start.auth_url, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(2)
                    current_url = str(page.url or "")

                    # Check if callback was directly obtained
                    callback_url = ""
                    if "code=" in current_url:
                        callback_url = current_url
                    else:
                        # May need to follow redirects
                        for _ in range(5):
                            time.sleep(1)
                            current_url = str(page.url or "")
                            if "code=" in current_url:
                                callback_url = current_url
                                break

                    if callback_url:
                        log("  Success: skipped add_phone, obtained OAuth callback")
                        return _submit_callback_result(callback_url, oauth_start, proxy)

                    # Check page state
                    skip_state = _derive_registration_state_from_page(page)
                    if skip_state.get("page_type") in {"consent", "workspace_selection", "organization_selection"}:
                        log("  Success: skipped add_phone, reached consent page")
                        # Try to complete consent flow in browser
                        browser_result = _complete_oauth_in_browser(page, oauth_start, proxy, log)
                        if browser_result:
                            return browser_result
                        # Fallback to curl session approach
                        cookies_dict = _get_cookies(page)
                        session_result = _complete_oauth_with_session(cookies_dict, oauth_start, proxy, log)
                        if session_result:
                            return session_result

                    if skip_state.get("page_type") == "add_phone":
                        log("  Skip failed, still on add_phone page")
                    else:
                        log(f"  Page state after skip: {skip_state.get('page_type') or '-'}")
                        # Continue state machine loop
                        continue

                except Exception as exc:
                    callback_url = _extract_callback_url_from_exception(exc)
                    if callback_url:
                        return _submit_callback_result(callback_url, oauth_start, proxy)
                    log(f"  Skip add_phone exception: {exc}")

                log("  Warning: add_phone cannot be skipped and no SMS service available")
                return None

            # chatgpt_home: page may be doing JS redirect (e.g. to add-phone)
            # Wait longer for redirect to complete
            if state["page_type"] == "chatgpt_home":
                # Check if this is an error page
                if "error" in current_url:
                    error_msg = current_url.split("error=")[-1].split("&")[0] if "error=" in current_url else "unknown"
                    log(f"  OAuth error page: {error_msg} url={current_url[:150]}")
                    raise RuntimeError(f"OpenAI OAuth error: {error_msg}")
                time.sleep(2)
                new_url = str(page.url or "")
                if new_url != current_url:
                    continue
                # Check if session cookie exists
                cookies_dict = _get_cookies(page)
                for ck, cv in cookies_dict.items():
                    if "session" in ck.lower() and cv:
                        log(f"  chatgpt_home detected session cookie: {ck}")
                        session_result = _complete_oauth_with_session(cookies_dict, oauth_start, proxy, log)
                        if session_result:
                            return session_result
                        break
                continue

            target_url = _normalize_url(state.get("continue_url") or "", OPENAI_AUTH)
            if target_url and target_url != current_url:
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as exc:
                    callback_url = _extract_callback_url_from_exception(exc)
                    if callback_url:
                        return _submit_callback_result(callback_url, oauth_start, proxy)
                    log(f"  OAuth navigation failed: {exc}")
                    break
                continue

            error_text = _extract_auth_error_text(page)
            if error_text:
                raise RuntimeError(f"OAuth page error: {error_text[:300]}")
            time.sleep(0.5)
    except Exception as e:
        log(f"  OAuth exception: {e}")
        return None

    cookies_dict = _get_cookies(page)
    result = _complete_oauth_with_session(cookies_dict, oauth_start, proxy, log)
    if result:
        return result

    session_token = cookies_dict.get("__Secure-next-auth.session-token", "")
    if not session_token:
        log("  Warning: no session_token, OAuth failed")
        return None
    log("  Warning: full OAuth failed, falling back to session access_token")
    return None


def _wait_for_access_token(page, timeout: int = 60) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = page.evaluate("""
            async () => {
                const r = await fetch('/api/auth/session');
                const j = await r.json();
                return j.accessToken || '';
            }
            """)
            if r:
                return r
        except Exception:
            pass
        time.sleep(2)
    return ""


def _is_registration_complete(state: dict) -> bool:
    page_type = str(state.get("page_type") or "")
    url = str(state.get("current_url") or state.get("continue_url") or "").lower()
    return page_type in {"callback", "oauth_callback", "chatgpt_home"} or (
        "chatgpt.com" in url and "redirect_uri" not in url and "about-you" not in url
    )


def _handle_post_signup_onboarding(page, log) -> None:
    current_url = str(page.url or "")
    if "chatgpt.com" not in current_url:
        return
    try:
        # May show persistent storage prompt, prefer Allow, Block is also fine for main flow.
        allow_selector = _click_first(
            page,
            [
                'button:has-text("Allow")',
                'button:has-text("allow")',
                'button:has-text("Block")',
                'button:has-text("block")',
            ],
            timeout=1,
        )
        if allow_selector:
            log(f"Handled browser popup: {allow_selector}")
    except Exception:
        pass

    # New accounts often show onboarding survey page, prefer Skip.
    try:
        if page.locator("text=What brings you to ChatGPT?").first.count() > 0:
            skip_selector = _click_first(
                page,
                [
                    'button:has-text("Skip")',
                    'button:has-text("skip")',
                    'button:has-text("Next")',
                    'button:has-text("next")',
                ],
                timeout=5,
            )
            if skip_selector:
                log(f"Handled onboarding page: {skip_selector}")
                _browser_pause(page)
    except Exception:
        pass


def _is_password_registration(state: dict) -> bool:
    return str(state.get("page_type") or "") in {"create_account_password", "password"}


def _is_email_otp(state: dict) -> bool:
    target = f"{state.get('continue_url') or ''} {state.get('current_url') or ''}".lower()
    return str(state.get("page_type") or "") == "email_otp_verification" or "email-verification" in target or "email-otp" in target


def _is_about_you(state: dict) -> bool:
    target = f"{state.get('continue_url') or ''} {state.get('current_url') or ''}".lower()
    return str(state.get("page_type") or "") == "about_you" or "about-you" in target


def _is_add_phone(state: dict) -> bool:
    target = f"{state.get('continue_url') or ''} {state.get('current_url') or ''}".lower()
    return str(state.get("page_type") or "") == "add_phone" or "add-phone" in target


def _mask_phone_number(phone_number: str) -> str:
    text = str(phone_number or "").strip()
    if len(text) <= 4:
        return text
    if len(text) <= 8:
        return f"{text[:2]}****{text[-2:]}"
    return f"{text[:4]}****{text[-2:]}"


def _is_invalid_phone_otp_response(result: dict) -> bool:
    status = int((result or {}).get("status") or 0)
    if status != 400:
        return False
    data = (result or {}).get("data")
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").lower()
            code = str(error.get("code") or "").lower()
            return code == "invalid_input" and "invalid otp code" in message
    text = str((result or {}).get("text") or "").lower()
    return "invalid otp code" in text


def _handle_add_phone_challenge(
    page,
    phone_callback,
    *,
    device_id: str,
    user_agent: str,
    log,
    resume_url: str = "",
) -> dict:
    if not phone_callback:
        raise RuntimeError(
            "ChatGPT registration encountered phone verification, but no phone_callback configured. "
            "Please configure SMS service in RegisterConfig.extra, or manually complete phone verification."
        )

    referer = _normalize_url(str(page.url or ""), OPENAI_AUTH) or f"{OPENAI_AUTH}/add-phone"
    headers = _build_browser_headers(
        user_agent=user_agent,
        accept="application/json",
        referer=referer,
        origin=OPENAI_AUTH,
        content_type="application/json",
        extra_headers={
            "sec-fetch-site": "same-origin",
            "oai-device-id": device_id,
            **_generate_datadog_trace_headers(),
        },
    )

    def _request_openai_resend():
        result = _browser_fetch(
            page,
            f"{OPENAI_AUTH}/api/accounts/phone-otp/resend",
            method="POST",
            headers=headers,
            body=None,
            redirect="follow",
        )
        log(f"  phone-otp/resend -> {int(result.get('status') or 0)}")

    if hasattr(phone_callback, "set_resend_callback"):
        phone_callback.set_resend_callback(_request_openai_resend)

    log("Registration flow entered add_phone, preparing to rent number and receive SMS code...")
    phone_number = str(phone_callback() or "").strip()
    if not phone_number:
        raise RuntimeError("Failed to get phone number")
    log(f"Detected add_phone, submitting phone number: {_mask_phone_number(phone_number)}")
    _browser_pause(page)
    send_result = _browser_fetch(
        page,
        f"{OPENAI_AUTH}/api/accounts/add-phone/send",
        method="POST",
        headers=headers,
        body=json.dumps({"phone_number": phone_number}),
        redirect="follow",
    )
    send_status = int(send_result.get("status") or 0)
    log(f"  add-phone/send -> {send_status}")
    if send_status not in (200, 201, 204):
        detail = (send_result.get("text") or "").strip()
        if hasattr(phone_callback, "mark_send_failed"):
            phone_callback.mark_send_failed(detail or f"HTTP {send_status}")
        raise RuntimeError(f"Phone number submit failed: {detail[:200] or f'HTTP {send_status}'}")
    if hasattr(phone_callback, "mark_send_succeeded"):
        phone_callback.mark_send_succeeded()

    log("Phone number submitted successfully, waiting for SMS code...")
    validate_result = None
    for code_attempt in range(3):
        sms_code = str(phone_callback() or "").strip()
        if not sms_code:
            raise RuntimeError("Failed to get SMS verification code")

        for attempt in range(3):
            _browser_pause(page)
            validate_result = _browser_fetch(
                page,
                f"{OPENAI_AUTH}/api/accounts/phone-otp/validate",
                method="POST",
                headers=headers,
                body=json.dumps({"code": sms_code}),
                redirect="follow",
            )
            validate_status = int(validate_result.get("status") or 0)
            log(f"  phone-otp/validate -> {validate_status}")
            if validate_status in (200, 201, 204):
                if hasattr(phone_callback, "report_success"):
                    phone_callback.report_success()
                break
            if _is_invalid_phone_otp_response(validate_result):
                log("SMS verification code was judged invalid, marking current SMS and waiting for the next one...")
                if hasattr(phone_callback, "mark_code_failed"):
                    phone_callback.mark_code_failed("invalid otp code")
                validate_result = None
                break
            if validate_status >= 500 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            detail = (validate_result.get("text") or "").strip()
            if hasattr(phone_callback, "mark_code_failed"):
                phone_callback.mark_code_failed(detail or f"HTTP {validate_status}")
            raise RuntimeError(f"SMS verification code validation failed: {detail[:200] or f'HTTP {validate_status}'}")

        if validate_result is not None and int(validate_result.get("status") or 0) in (200, 201, 204):
            break
    else:
        raise RuntimeError("SMS verification code validation failed: multiple codes were invalid or did not pass")

    state = _extract_flow_state(
        (validate_result or {}).get("data"),
        (validate_result or {}).get("url", page.url),
    )
    next_url = _normalize_url(resume_url, OPENAI_AUTH) if resume_url else ""
    if next_url:
        page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
        return _extract_flow_state(None, page.url)
    return state


def _requires_registration_navigation(state: dict) -> bool:
    if str(state.get("method") or "GET").upper() != "GET":
        return False
    if str(state.get("page_type") or "") == "external_url" and state.get("continue_url"):
        return True
    continue_url = str(state.get("continue_url") or "")
    current_url = str(state.get("current_url") or "")
    return bool(continue_url and continue_url != current_url)


def _browser_add_cookies(page, cookies: list[dict]) -> None:
    try:
        page.context.add_cookies(cookies)
    except Exception:
        pass


def _seed_browser_device_id(page, device_id: str) -> None:
    _browser_add_cookies(
        page,
        [
            {"name": "oai-did", "value": device_id, "domain": "chatgpt.com", "path": "/"},
            {"name": "oai-did", "value": device_id, "domain": ".chatgpt.com", "path": "/"},
            {"name": "oai-did", "value": device_id, "domain": "openai.com", "path": "/"},
            {"name": "oai-did", "value": device_id, "domain": "auth.openai.com", "path": "/"},
            {"name": "oai-did", "value": device_id, "domain": ".auth.openai.com", "path": "/"},
        ],
    )


def _get_browser_csrf_token(page) -> str:
    result = _browser_fetch(
        page,
        f"{CHATGPT_APP}/api/auth/csrf",
        method="GET",
        headers={
            "accept": "application/json",
            "referer": f"{CHATGPT_APP}/",
            "sec-fetch-site": "same-origin",
        },
        redirect="follow",
    )
    if result.get("ok") and isinstance(result.get("data"), dict):
        return str((result.get("data") or {}).get("csrfToken") or "").strip()
    return ""


def _start_browser_signin(page, email: str, device_id: str, csrf_token: str) -> str:
    from urllib.parse import urlencode

    query = urlencode(
        {
            "prompt": "login",
            "ext-oai-did": device_id,
            "auth_session_logging_id": str(uuid.uuid4()),
            "screen_hint": "login_or_signup",
            "login_hint": email,
        }
    )
    body = urlencode(
        {
            "callbackUrl": f"{CHATGPT_APP}/",
            "csrfToken": csrf_token,
            "json": "true",
        }
    )
    result = _browser_fetch(
        page,
        f"{CHATGPT_APP}/api/auth/signin/openai?{query}",
        method="POST",
        headers={
            "accept": "application/json",
            "referer": f"{CHATGPT_APP}/",
            "origin": CHATGPT_APP,
            "content-type": "application/x-www-form-urlencoded",
            "sec-fetch-site": "same-origin",
        },
        body=body,
        redirect="follow",
    )
    if result.get("ok") and isinstance(result.get("data"), dict):
        return str((result.get("data") or {}).get("url") or "").strip()
    return ""


def _browser_authorize(page, auth_url: str, log) -> str:
    if not auth_url:
        return ""
    try:
        page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
        final_url = page.url
        log(f"Authorize -> {final_url[:120]}")
        return final_url
    except Exception as exc:
        log(f"Authorize failed: {exc}")
        return ""


def _validate_browser_email_otp(page, code: str, device_id: str, user_agent: str, referer: str) -> dict:
    headers = _build_browser_headers(
        user_agent=user_agent,
        accept="application/json",
        referer=referer or f"{OPENAI_AUTH}/email-verification",
        origin=OPENAI_AUTH,
        content_type="application/json",
        extra_headers={
            "sec-fetch-site": "same-origin",
            "oai-device-id": device_id,
            **_generate_datadog_trace_headers(),
        },
    )
    sentinel = _build_browser_sentinel_token(page, device_id, "email_otp_validate", user_agent)
    if sentinel:
        headers["openai-sentinel-token"] = sentinel
    _browser_pause(page)
    return _browser_fetch(
        page,
        f"{OPENAI_AUTH}/api/accounts/email-otp/validate",
        method="POST",
        headers=headers,
        body=json.dumps({"code": code}),
        redirect="follow",
    )


def _submit_browser_about_you(page, device_id: str, user_agent: str, referer: str) -> dict:
    from .constants import generate_random_user_info

    headers = _build_browser_headers(
        user_agent=user_agent,
        accept="application/json",
        referer=referer or f"{OPENAI_AUTH}/about-you",
        origin=OPENAI_AUTH,
        content_type="application/json",
        extra_headers={
            "sec-fetch-site": "same-origin",
            "oai-device-id": device_id,
            **_generate_datadog_trace_headers(),
        },
    )
    sentinel = _build_browser_sentinel_token(page, device_id, "oauth_create_account", user_agent)
    if sentinel:
        headers["openai-sentinel-token"] = sentinel
    user_info = generate_random_user_info()
    _browser_pause(page)
    return _browser_fetch(
        page,
        f"{OPENAI_AUTH}/api/accounts/create_account",
        method="POST",
        headers=headers,
        body=json.dumps(user_info),
        redirect="follow",
    )


def _complete_oauth_in_browser(page, oauth_start, proxy, log) -> dict | None:
    """Complete OAuth consent flow in browser, multi-strategy retry clicking Continue.

    Reference Chrome extension project step9 implementation:
    - consent page is a <form action="/sign-in-with-chatgpt/.../consent">
    - prefer form.requestSubmit(button) over button.click()
    - multi-round retry: requestSubmit -> click -> dispatchEvent -> refresh retry
    """
    from .oauth import submit_callback_url

    CONSENT_FORM_SEL = OAUTH_CONSENT_FORM_SELECTOR
    MAX_ROUNDS = 4
    CLICK_EFFECT_TIMEOUT = 12

    def _try_extract_callback(url: str) -> dict | None:
        if not url or "code=" not in url:
            return None
        try:
            return json.loads(submit_callback_url(
                callback_url=url,
                expected_state=oauth_start.state,
                code_verifier=oauth_start.code_verifier,
                proxy_url=proxy,
            ))
        except Exception:
            return None

    def _check_current_url() -> dict | None:
        url = str(page.url or "")
        result = _try_extract_callback(url)
        if result:
            return result
        cb = _extract_callback_url_from_exception(Exception(url))
        return _try_extract_callback(cb) if cb else None

    def _wait_for_callback(timeout_sec: int) -> dict | None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            result = _check_current_url()
            if result:
                return result
            time.sleep(0.8)
        return None

    def _find_consent_button():
        """Find Continue button on consent page by priority"""
        # Strategy 1: find submit button within consent form
        _sel = CONSENT_FORM_SEL
        btn = page.evaluate("""(sel) => {
            const form = document.querySelector(sel);
            if (!form) return null;
            const buttons = form.querySelectorAll('button[type="submit"], input[type="submit"], [role="button"]');
            for (const el of buttons) {
                if (el.offsetParent === null) continue;
                const text = (el.textContent || '').trim().toLowerCase();
                const ddName = el.getAttribute('data-dd-action-name') || '';
                if (ddName === 'Continue' || /continue/i.test(text)) return 'form-continue';
            }
            const first = Array.from(buttons).find(el => el.offsetParent !== null);
            if (first) return 'form-submit';
            return null;
        }""", _sel)
        if btn:
            return btn
        # Strategy 2: globally find Continue button
        for sel in [
            'button[type="submit"][data-dd-action-name="Continue"]',
            'button:has-text("Continue")',
            'button:has-text("Continue")',
            'button:has-text("Allow")',
            'button:has-text("Authorize")',
            'button[type="submit"]',
        ]:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=500):
                    return sel
            except Exception:
                continue
        return None

    def _click_strategy_request_submit(log_round: int) -> bool:
        """Strategy 1: form.requestSubmit(button) - most reliable form submit method"""
        try:
            result = page.evaluate("""(sel) => {
                const form = document.querySelector(sel);
                if (!form) return 'no-form';
                const buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
                let target = null;
                for (const el of buttons) {
                    if (el.offsetParent === null) continue;
                    const text = (el.textContent || '').trim().toLowerCase();
                    const ddName = el.getAttribute('data-dd-action-name') || '';
                    if (ddName === 'Continue' || /continue/i.test(text)) { target = el; break; }
                }
                if (!target) target = Array.from(buttons).find(el => el.offsetParent !== null);
                if (!target) return 'no-button';
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit(target);
                    return 'requestSubmit';
                }
                target.click();
                return 'click-fallback';
            }""", CONSENT_FORM_SEL)
            log(f"  consent round {log_round}round requestSubmit: {result}")
            return result not in ("no-form", "no-button")
        except Exception as e:
            log(f"  consent requestSubmit exception: {e}")
            return False

    def _click_strategy_playwright(log_round: int) -> bool:
        """Strategy 2: Playwright locator.click()"""
        for sel in [
            'button:has-text("Continue")',
            'button:has-text("Continue")',
            'button[type="submit"]',
        ]:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=1500):
                    loc.click()
                    log(f"  consent round {log_round}round playwright click: {sel}")
                    return True
            except Exception:
                continue
        return False

    def _click_strategy_js_dispatch(log_round: int) -> bool:
        """Strategy 3: JS dispatchEvent simulated click"""
        try:
            result = page.evaluate("""() => {
                const buttons = document.querySelectorAll('button, [role="button"]');
                for (const el of buttons) {
                    if (el.offsetParent === null) continue;
                    const text = (el.textContent || '').trim().toLowerCase();
                    const ddName = el.getAttribute('data-dd-action-name') || '';
                    if (ddName === 'Continue' || /continue/i.test(text)) {
                        el.focus();
                        el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                        return text || 'dispatched';
                    }
                }
                return null;
            }
            """)
            if result:
                log(f"  consent round {log_round}round JS dispatch: {result}")
                return True
            return False
        except Exception:
            return False

    strategies = [
        _click_strategy_request_submit,
        _click_strategy_playwright,
        _click_strategy_js_dispatch,
        _click_strategy_request_submit,
    ]

    try:
        current_url = str(page.url or "")
        log(f"  browser consent handling: {current_url[:100]}")

        # First check if current URL already has code
        result = _check_current_url()
        if result:
            log("  ✓ page is already at callback URL")
            return result

        # wait for page load
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        time.sleep(1)

        # check "Try again" button
        try:
            try_again = page.query_selector('button:has-text("Try again")')
            if try_again and try_again.is_visible():
                log("  consent page has error, clicking Try again...")
                try_again.click()
                time.sleep(3)
        except Exception:
            pass

        # multi-round strategy retry
        for round_idx in range(MAX_ROUNDS):
            result = _check_current_url()
            if result:
                log("  ✓ browser OAuth consent completed")
                return result

            strategy_fn = strategies[min(round_idx, len(strategies) - 1)]
            clicked = strategy_fn(round_idx + 1)

            if clicked:
                time.sleep(2)
                result = _wait_for_callback(CLICK_EFFECT_TIMEOUT)
                if result:
                    log("  ✓ browser OAuth consent completed")
                    return result
                log(f"  consent round {round_idx + 1}round click did not redirect page")
            else:
                log(f"  consent round {round_idx + 1}round button not found")

            # refresh page before last round retry
            if round_idx < MAX_ROUNDS - 1:
                log(f"  consent refresh page preparing for round {round_idx + 2}...")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(2)

        log(f"  consent {MAX_ROUNDS}round attempts still not completed, current: {str(page.url or '')[:100]}")
        return None
    except Exception as exc:
        cb = _extract_callback_url_from_exception(exc)
        if cb:
            result = _try_extract_callback(cb)
            if result:
                log("  ✓ extracted callback from exception, OAuth completed")
                return result
        log(f"  browser OAuth consent exception: {exc}")
        return None


def _submit_oauth_password_direct(page, password: str, log) -> dict:
    """OAuth flow specific: directly fill password for login, do not attempt to recover to signup state."""
    input_selector = _wait_for_any_selector(page, PASSWORD_INPUT_SELECTORS, timeout=15)
    if not input_selector:
        # Password input not appeared, page may still be loading or redirected
        # wait and retry
        time.sleep(2)
        input_selector = _wait_for_any_selector(page, PASSWORD_INPUT_SELECTORS, timeout=10)
    if not input_selector:
        raise RuntimeError("OAuth password page input not found")
    if not _fill_input_like_user(page, input_selector, password):
        raise RuntimeError("OAuth password page fill failed")
    log(f"  OAuth password page input: {input_selector}")
    _browser_pause(page)

    submit_selector = _click_first(page, PASSWORD_SUBMIT_SELECTORS, timeout=8)
    if submit_selector:
        log(f"  OAuth Password page clicked continue button: {submit_selector}")
    elif _submit_form_with_fallback(page, input_selector):
        log("  OAuth password page used form fallback submit")
    else:
        raise RuntimeError("OAuth Password page Continue button not found")

    deadline = time.time() + 20
    while time.time() < deadline:
        current_url = str(page.url or "")
        state = _derive_registration_state_from_page(page)
        page_type = str(state.get("page_type") or "")
        if page_type in {"email_otp_verification", "about_you", "consent", "workspace_selection",
                         "organization_selection", "add_phone", "oauth_callback", "chatgpt_home", "external_url"}:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        if "code=" in current_url:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        error_text = _extract_auth_error_text(page)
        if error_text:
            return {"ok": False, "status": 400, "url": current_url, "data": None, "text": error_text}
        time.sleep(0.5)
    return {"ok": False, "status": 0, "url": str(page.url or ""), "data": None, "text": "OAuth password submit did not redirect"}


def _submit_password_via_page(page, password: str, log) -> dict:
    if _recover_signup_password_page(page, log):
        time.sleep(1)

    input_selector = _wait_for_any_selector(page, PASSWORD_INPUT_SELECTORS, timeout=15)
    if not input_selector:
        raise RuntimeError("Password page input not found")
    if not _fill_input_like_user(page, input_selector, password):
        raise RuntimeError("Password page fill failed")
    log(f"Password page input: {input_selector}")
    _browser_pause(page)

    start_url = str(page.url or "")
    submit_selector = _click_first(page, PASSWORD_SUBMIT_SELECTORS, timeout=8)
    if submit_selector:
        log(f"Password page clicked continue button: {submit_selector}")
    elif _submit_form_with_fallback(page, input_selector):
        log("Password page no clickable Continue found, used form fallback submit")
    else:
        raise RuntimeError("Password page Continue button not found")

    deadline = time.time() + 20
    last_url = str(page.url or "")
    while time.time() < deadline:
        current_url = str(page.url or "")
        last_url = current_url or last_url
        state = _derive_registration_state_from_page(page)
        page_type = str(state.get("page_type") or "")
        if page_type in {"email_otp_verification", "about_you", "add_phone", "oauth_callback", "chatgpt_home"}:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        if current_url != start_url and page_type and page_type not in {"create_account_password", "login_password"}:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        if page_type == "login_password" and _recover_signup_password_page(page, log):
            input_selector = _wait_for_any_selector(page, PASSWORD_INPUT_SELECTORS, timeout=5)
            if not input_selector:
                return {"ok": False, "status": 400, "url": current_url, "data": None, "text": "Login password page recovery: signup password input not found"}
            if not _fill_input_like_user(page, input_selector, password):
                return {"ok": False, "status": 400, "url": current_url, "data": None, "text": "Login password page recovery: password re-fill failed"}
            submit_selector = _click_first(page, PASSWORD_SUBMIT_SELECTORS, timeout=5)
            if submit_selector:
                log(f"Re-clicked password submit button after recovery: {submit_selector}")
                start_url = str(page.url or start_url)
                time.sleep(0.4)
                continue
            if _submit_form_with_fallback(page, input_selector):
                log("Password submit button not found after recovery, used form fallback submit")
                start_url = str(page.url or start_url)
                time.sleep(0.4)
                continue
            return {"ok": False, "status": 400, "url": current_url, "data": None, "text": "Login password page recovery: no submit method found"}
        error_text = _extract_auth_error_text(page)
        if error_text:
            _dump_debug(page, "chatgpt_password_fail")
            return {"ok": False, "status": 400, "url": current_url, "data": None, "text": error_text}
        time.sleep(0.5)
    _dump_debug(page, "chatgpt_password_fail")
    return {"ok": False, "status": 0, "url": last_url, "data": None, "text": "Password page submit did not redirect"}


def _submit_otp_via_page(page, code: str, log) -> dict:
    otp = str(code or "").strip()
    if not otp:
        return {"ok": False, "status": 400, "url": page.url, "data": None, "text": "Verification code is empty"}

    filled = False

    # First try 6-digit OTP input fields
    try:
        digit_inputs = page.locator(
            "input[inputmode='numeric'], input[autocomplete='one-time-code'], input[type='tel'], input[type='number']"
        )
        count = digit_inputs.count()
        if count >= len(otp):
            done = 0
            for i in range(min(count, len(otp))):
                box = digit_inputs.nth(i)
                try:
                    box.wait_for(state="visible", timeout=800)
                    box.fill("")
                    box.type(otp[i], delay=random.randint(20, 60))
                    done += 1
                except Exception:
                    break
            if done >= len(otp):
                filled = True
                log(f"Verification code page filled {done} digit segmented input fields")
    except Exception:
        pass

    # Then try single input field
    if not filled:
        otp_candidates = [
            page.get_by_label(re.compile(r"verification code|code|otp", re.IGNORECASE)),
            page.get_by_role("textbox", name=re.compile(r"verification code|code|otp", re.IGNORECASE)),
            page.locator("input[autocomplete='one-time-code']"),
            page.locator("input[name*='code' i]"),
            page.locator("input[id*='code' i]"),
            page.locator("input[type='text']"),
            page.locator("input"),
        ]
        for candidate in otp_candidates:
            try:
                target = candidate.first
                target.wait_for(state="visible", timeout=1200)
                target.click(timeout=1200)
                target.fill("")
                target.type(otp, delay=random.randint(18, 45))
                final_value = str(target.input_value() or "").strip()
                if final_value:
                    filled = True
                    log("Verification code page filled single input field")
                    break
            except Exception:
                continue

    if not filled:
        return {"ok": False, "status": 0, "url": page.url, "data": None, "text": "Verification code page: no fillable input field found"}

    _browser_pause(page)
    submit_selector = _click_first(
        page,
        [
            'button[type="submit"]',
            'button[data-testid="continue-button"]',
            'button:has-text("Continue")',
            'button:has-text("continue")',
            'button:has-text("Verify")',
            'button:has-text("verify")',
            'button:has-text("Next")',
            'button:has-text("next")',
        ],
        timeout=8,
    )
    if not submit_selector:
        return {"ok": False, "status": 0, "url": page.url, "data": None, "text": "Verification code page Continue button not found"}
    log(f"Verification code page clicked continue button: {submit_selector}")

    deadline = time.time() + 20
    last_url = page.url
    while time.time() < deadline:
        current_url = page.url
        last_url = current_url or last_url
        if "about-you" in current_url:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        if "add-phone" in current_url or "chatgpt.com" in current_url or "code=" in current_url:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        if "consent" in current_url or "sign-in-with-chatgpt" in current_url or "workspace" in current_url or "organization" in current_url:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        try:
            error_text = page.locator("text=Invalid code").first.text_content(timeout=400)
        except Exception:
            error_text = ""
        if error_text:
            return {"ok": False, "status": 400, "url": current_url, "data": None, "text": error_text}
        time.sleep(0.5)
    return {"ok": False, "status": 0, "url": last_url, "data": None, "text": "Verification code page submit did not redirect"}


def _submit_about_you_via_page(page, log) -> dict:
    from .constants import generate_random_user_info

    user_info = generate_random_user_info()
    name = str(user_info.get("name") or "").strip()
    birthdate = str(user_info.get("birthdate") or "").strip()
    if not name or not birthdate:
        raise RuntimeError("about_you data generation failed")
    date_parts = birthdate.split("-")
    if len(date_parts) == 3:
        yyyy, mm, dd = date_parts
        us_birthdate = f"{mm}/{dd}/{yyyy}"
        cn_birthdate = f"{yyyy}/{mm}/{dd}"
    else:
        us_birthdate = birthdate
        cn_birthdate = birthdate.replace("-", "/")
    log(f"about_you form: name={name}, birthdate={birthdate}, ui_birthdate={us_birthdate}, cn_birthdate={cn_birthdate}")

    def _fill_locator(locator, value: str) -> bool:
        try:
            target = locator.first
            target.wait_for(state="visible", timeout=1500)
            target.click(timeout=1500)
            _browser_pause(page, headed=False)
            try:
                applied = bool(
                    target.evaluate(
                        """
                        (input, nextValue) => {
                          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                          if (!setter) return false;
                          setter.call(input, nextValue);
                          input.dispatchEvent(new Event('input', { bubbles: true }));
                          input.dispatchEvent(new Event('change', { bubbles: true }));
                          return String(input.value || '') === String(nextValue || '');
                        }
                        """,
                        value,
                    )
                )
            except Exception:
                applied = False
            if not applied:
                target.fill("")
                target.type(value, delay=random.randint(25, 70))
            try:
                target.dispatch_event("blur")
            except Exception:
                pass
            final_val = str(target.input_value() or "").strip()
            return final_val == str(value).strip()
        except Exception:
            return False

    def _locator_from_visible_input_entry(entry: dict):
        try:
            visible_index = int(entry.get("visibleIndex"))
        except Exception:
            return None
        return page.locator("input:visible:not([type='hidden']):not([disabled]):not([readonly])").nth(visible_index)

    def _fill_visible_input_entry(entry: dict | None, value: str) -> bool:
        if not entry:
            return False
        locator = _locator_from_visible_input_entry(entry)
        if locator is None:
            return False
        return _fill_locator(locator, value)

    def _resolve_visible_input_selector(selectors: list[str]) -> str | None:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=500)
                return selector
            except Exception:
                continue
        return None

    def _fill_second_visible_input(values: list[str], excluded_visible_indices: set[int] | None = None) -> bool:
        """Fallback: about_you card typically has Full name + Birthday/Age two input fields."""
        try:
            locator = page.locator(
                "input:visible:not([type='hidden']):not([disabled]):not([readonly])"
            )
            count = locator.count()
            if count < 2:
                return False
            excluded = {int(value) for value in (excluded_visible_indices or set())}
            target_index = None
            for idx in range(count):
                if idx not in excluded:
                    target_index = idx
                    if idx > 0:
                        break
            if target_index is None:
                return False
            target = locator.nth(target_index)
            target.click(timeout=1200)
            _browser_pause(page, headed=False)
            for value in values:
                try:
                    target.fill("")
                except Exception:
                    pass
                try:
                    target.type(str(value), delay=random.randint(18, 45))
                except Exception:
                    continue
                final_val = str(target.input_value() or "").strip()
                if final_val:
                    return True
            return False
        except Exception:
            return False

    def _has_visible(locator) -> bool:
        try:
            locator.first.wait_for(state="visible", timeout=700)
            return True
        except Exception:
            return False

    def _fill_birthday_selects(yyyy: str, mm: str, dd: str) -> bool:
        """Handle Month/Day/Year dropdown style birthday controls."""
        try:
            select_locator = page.locator("select:visible")
            count = select_locator.count()
            if count < 2:
                return False

            month_num = int(mm)
            day_num = int(dd)
            year_num = int(yyyy)
            month_short = time.strftime("%b", time.strptime(str(month_num), "%m"))
            month_full = time.strftime("%B", time.strptime(str(month_num), "%m"))

            assigned = {"month": False, "day": False, "year": False}

            for i in range(count):
                sel = select_locator.nth(i)
                try:
                    options = sel.locator("option")
                    option_count = options.count()
                except Exception:
                    option_count = 0
                if option_count <= 0:
                    continue

                texts: list[str] = []
                for idx in range(min(option_count, 80)):
                    try:
                        texts.append(str(options.nth(idx).inner_text(timeout=300) or "").strip())
                    except Exception:
                        continue
                joined = " ".join(texts).lower()

                try:
                    if (not assigned["month"]) and (
                        "january" in joined or "february" in joined or "march" in joined or "april" in joined
                    ):
                        for candidate in (month_full, month_short, str(month_num), f"{month_num:02d}"):
                            try:
                                sel.select_option(label=candidate, timeout=800)
                                assigned["month"] = True
                                break
                            except Exception:
                                try:
                                    sel.select_option(value=candidate, timeout=800)
                                    assigned["month"] = True
                                    break
                                except Exception:
                                    continue
                        continue

                    if (not assigned["year"]) and any(str(y) in joined for y in (year_num, year_num - 1, year_num + 1, 2026, 2025)):
                        for candidate in (str(year_num),):
                            try:
                                sel.select_option(label=candidate, timeout=800)
                                assigned["year"] = True
                                break
                            except Exception:
                                try:
                                    sel.select_option(value=candidate, timeout=800)
                                    assigned["year"] = True
                                    break
                                except Exception:
                                    continue
                        continue

                    if (not assigned["day"]) and any(str(x) in joined for x in (" 1 ", "2", "30", "31")):
                        for candidate in (str(day_num), f"{day_num:02d}"):
                            try:
                                sel.select_option(label=candidate, timeout=800)
                                assigned["day"] = True
                                break
                            except Exception:
                                try:
                                    sel.select_option(value=candidate, timeout=800)
                                    assigned["day"] = True
                                    break
                                except Exception:
                                    continue
                except Exception:
                    continue

            # Dropdown order fallback: month/day/year
            if count >= 3:
                try:
                    if not assigned["month"]:
                        select_locator.nth(0).select_option(label=month_short, timeout=800)
                        assigned["month"] = True
                except Exception:
                    pass
                try:
                    if not assigned["day"]:
                        select_locator.nth(1).select_option(label=str(day_num), timeout=800)
                        assigned["day"] = True
                except Exception:
                    pass
                try:
                    if not assigned["year"]:
                        select_locator.nth(2).select_option(label=str(year_num), timeout=800)
                        assigned["year"] = True
                except Exception:
                    pass

            return assigned["month"] and assigned["day"] and assigned["year"]
        except Exception:
            return False

    visible_inputs = _collect_visible_text_inputs(page)
    if visible_inputs:
        log(
            "about_you visible inputs: "
            + " | ".join(
                f"#{int(item.get('visibleIndex', 0))} {(_about_you_input_hints(item) or '-')[:80]}"
                for item in visible_inputs[:4]
            )
        )
    ordered_visible_entries = sorted(
        [item for item in visible_inputs if str(item.get("visibleIndex", "")).isdigit()],
        key=lambda item: int(item.get("visibleIndex", 0)),
    )
    name_entry = _pick_best_about_you_input(visible_inputs, "name")
    age_entry = _pick_best_about_you_input(
        visible_inputs,
        "age",
        exclude_visible_indices={int(name_entry.get("visibleIndex"))} if name_entry and str(name_entry.get("visibleIndex", "")).isdigit() else set(),
    )

    name_candidates = [
        page.get_by_label(re.compile(r"full\s*name", re.IGNORECASE)),
        page.get_by_label(re.compile(r"full name", re.IGNORECASE)),
        page.get_by_role("textbox", name=re.compile(r"full\s*name|name", re.IGNORECASE)),
        page.get_by_role("textbox", name=re.compile(r"full name", re.IGNORECASE)),
        page.locator("input[autocomplete='name']"),
        page.locator("input[name*='name' i]"),
        page.locator("input[id*='name' i]"),
        page.locator("input[name*='name']"),
        page.locator("input[id*='name']"),
        page.locator(
            "xpath=//*[contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'full name')]/following::input[1]"
        ),
        page.locator("xpath=//*[contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'full name')]/following::input[1]"),
    ]
    birthday_candidates = [
        page.get_by_label(re.compile(r"birthday|date of birth|birth", re.IGNORECASE)),
        page.get_by_label(re.compile(r"birthday|date of birth", re.IGNORECASE)),
        page.get_by_role("textbox", name=re.compile(r"birthday|date of birth|birth", re.IGNORECASE)),
        page.get_by_role("textbox", name=re.compile(r"birthday|date of birth", re.IGNORECASE)),
        page.get_by_placeholder(re.compile(r"mm.?dd.?yyyy|yyyy.?mm.?dd|birthday", re.IGNORECASE)),
        page.locator("input[name*='birth' i]"),
        page.locator("input[id*='birth' i]"),
        page.locator("input[placeholder*='MM' i]"),
        page.locator("input[placeholder*='DD' i]"),
        page.locator("input[placeholder*='YYYY' i]"),
        page.locator("input[placeholder*='YYYY']"),
        page.locator("input[placeholder*='MM']"),
        page.locator("input[placeholder*='DD']"),
        page.locator("input[inputmode='numeric']"),
        page.locator(
            "xpath=//*[contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'birthday')]/following::input[1]"
        ),
        page.locator("xpath=//*[contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'birthday')]/following::input[1]"),
        page.locator("input[type='date']"),
    ]

    age_years = None
    try:
        birth_year = int(str(birthdate).split("-")[0])
        current_year = int(time.strftime("%Y"))
        age_years = max(25, min(40, current_year - birth_year))
    except Exception:
        age_years = random.randint(25, 35)

    age_candidates = [
        page.get_by_label(re.compile(r"age", re.IGNORECASE)),
        page.get_by_label(re.compile(r"age", re.IGNORECASE)),
        page.get_by_role("textbox", name=re.compile(r"age", re.IGNORECASE)),
        page.get_by_role("textbox", name=re.compile(r"age", re.IGNORECASE)),
        page.locator("input[name*='age' i]"),
        page.locator("input[id*='age' i]"),
        page.locator("input[placeholder*='Age' i]"),
        page.locator("input[placeholder*='Age']"),
        page.locator(
            "xpath=//*[contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'age')]/following::input[1]"
        ),
        page.locator("xpath=//*[contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'age')]/following::input[1]"),
    ]

    fill_result = {"name": False, "birthdate": False, "age": False, "month": False, "day": False, "year": False}
    if _fill_visible_input_entry(name_entry, name):
        fill_result["name"] = True
    if not fill_result.get("name"):
        for candidate in name_candidates:
            if _fill_locator(candidate, name):
                fill_result["name"] = True
                break
    mode_probe = {}
    try:
        mode_probe = page.evaluate(
            """
            () => {
              const labels = Array.from(document.querySelectorAll('label'))
                .map((n) => String(n.textContent || '').trim().toLowerCase())
                .filter(Boolean);
              const placeholders = Array.from(document.querySelectorAll('input'))
                .map((n) => String(n.placeholder || '').trim().toLowerCase())
                .filter(Boolean);
              const headings = Array.from(document.querySelectorAll('h1,h2,h3'))
                .map((n) => String(n.textContent || '').trim().toLowerCase())
                .filter(Boolean);
              const allText = labels.concat(placeholders).concat(headings);
              const hasAge = allText.some((t) => t === 'age' || t.includes('how old'));
              const hasBirthday = allText.some((t) =>
                t.includes('birthday') || t.includes('date of birth') || t.includes('birth')
              );
              return { labels, placeholders, headings, hasAge, hasBirthday };
            }
            """
        ) or {}
    except Exception:
        mode_probe = {}

    has_age_label = bool(mode_probe.get("hasAge"))
    has_birthday_label = bool(mode_probe.get("hasBirthday"))
    has_age_field = any(_has_visible(candidate) for candidate in age_candidates[:3])
    has_birthday_field = any(_has_visible(candidate) for candidate in birthday_candidates[:3])
    has_birthday_select = False
    try:
        has_birthday_select = page.locator("select:visible").count() >= 2
    except Exception:
        has_birthday_select = False
    if has_birthday_select:
        about_mode = "birthday_select"
    elif (has_age_label and not has_birthday_label) or (has_age_field and not has_birthday_field):
        about_mode = "age"
    else:
        about_mode = "birthday"
    log(f"about_you page mode: {about_mode} labels={mode_probe.get('labels', [])[:4]}")
    direct_name_selector = _resolve_visible_input_selector(
        [
            'input[name="name"]',
            'input[name="full_name"]',
            'input[autocomplete="name"]',
            'input[placeholder*="name" i]',
            'input[placeholder*="name" i]',
            'input[id*="name" i]:not([type="hidden"])',
        ]
    )
    direct_age_selector = _resolve_visible_input_selector(
        [
            'input[name="age"]',
            'input[placeholder="Age"]',
            'input[placeholder="age"]',
            'input[placeholder*="Age"]',
            'input[id*="age" i]',
        ]
    )
    if about_mode == "age" and len(ordered_visible_entries) >= 2:
        name_entry = ordered_visible_entries[0]
        age_entry = ordered_visible_entries[1]
        log(
            f"about_you age input mapping: name=#{int(name_entry.get('visibleIndex', 0))}, "
            f"age=#{int(age_entry.get('visibleIndex', 0))}"
        )
    if about_mode == "age":
        log(
            "about_you age direct targeting: "
            f"name={direct_name_selector or '-'}, age={direct_age_selector or '-'}"
        )

    def _fill_segmented_date(mm: str, dd: str, yyyy: str) -> bool:
        """Handle MM / DD / YYYY segmented date input fields (React DateField style).
        Characteristic: multiple small inputs or div[data-type] segments under a Birthday label."""
        try:
            # Method 1: div[data-type] segment (React Aria DateField)
            month_seg = page.locator('div[data-type="month"], input[data-type="month"]')
            day_seg = page.locator('div[data-type="day"], input[data-type="day"]')
            year_seg = page.locator('div[data-type="year"], input[data-type="year"]')
            if month_seg.count() > 0 and day_seg.count() > 0 and year_seg.count() > 0:
                month_seg.first.click(force=True)
                page.keyboard.type(mm, delay=50)
                time.sleep(0.3)
                day_seg.first.click(force=True)
                page.keyboard.type(dd, delay=50)
                time.sleep(0.3)
                year_seg.first.click(force=True)
                page.keyboard.type(yyyy, delay=50)
                return True

            # Method 2: single date input with MM/DD/YYYY placeholder
            # Click input, then type MM DD YYYY in order (Tab to switch segments)
            date_input = page.locator("input[placeholder*='MM'], input[placeholder*='mm'], input[type='date']")
            if date_input.count() > 0:
                date_input.first.click(force=True)
                time.sleep(0.2)
                page.keyboard.type(mm, delay=50)
                page.keyboard.type(dd, delay=50)
                page.keyboard.type(yyyy, delay=50)
                return True

            # Method 3: second visible input under Birthday label, click and type digits
            birthday_input = page.get_by_label(re.compile(r"birthday|birth", re.IGNORECASE))
            if birthday_input.count() > 0:
                birthday_input.first.click(force=True)
                time.sleep(0.2)
                page.keyboard.type(mm, delay=50)
                page.keyboard.type(dd, delay=50)
                page.keyboard.type(yyyy, delay=50)
                return True

            # Method 4: second visible input (name is the first)
            inputs = page.locator("input:visible:not([type='hidden']):not([disabled])")
            if inputs.count() >= 2:
                target = inputs.nth(1)
                target.click(force=True)
                time.sleep(0.3)
                # First clear
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
                time.sleep(0.1)
                # Type MM, Tab to DD, Tab to YYYY
                page.keyboard.type(mm, delay=80)
                time.sleep(0.3)
                page.keyboard.type(dd, delay=80)
                time.sleep(0.3)
                page.keyboard.type(yyyy, delay=80)
                time.sleep(0.3)
                # Verify if correct value was filled
                val = str(target.input_value() or "").strip()
                if val and val != target.get_attribute("placeholder"):
                    return True
                # If direct input does not work, try Tab switching
                target.click(force=True)
                time.sleep(0.2)
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
                for i, part in enumerate([mm, dd, yyyy]):
                    page.keyboard.type(part, delay=80)
                    if i < 2:
                        page.keyboard.press("Tab")
                        time.sleep(0.2)
                return True
        except Exception:
            pass
        return False

    if about_mode == "birthday_select":
        if len(date_parts) == 3 and _fill_birthday_selects(yyyy, mm, dd):
            fill_result["month"] = True
            fill_result["day"] = True
            fill_result["year"] = True
            fill_result["birthdate"] = True
    elif about_mode == "age":
        if direct_name_selector and _fill_input_like_user(page, direct_name_selector, name):
            fill_result["name"] = True
        elif _fill_visible_input_entry(name_entry, name):
            fill_result["name"] = True
        if age_years is not None:
            if direct_age_selector and _fill_input_like_user(page, direct_age_selector, str(age_years)):
                fill_result["age"] = True
            elif _fill_visible_input_entry(age_entry, str(age_years)):
                fill_result["age"] = True
            if not fill_result.get("age") and len(ordered_visible_entries) < 2:
                for candidate in age_candidates:
                    if _fill_locator(candidate, str(age_years)):
                        fill_result["age"] = True
                        break
        # fallback: directly find input with placeholder="Age"
        if not fill_result.get("age") and age_years is not None and len(ordered_visible_entries) < 2:
            try:
                age_input = page.locator("input[placeholder='Age'], input[placeholder='age']")
                if age_input.count() > 0:
                    age_input.first.click(force=True)
                    time.sleep(0.2)
                    age_input.first.fill("")
                    age_input.first.type(str(age_years), delay=random.randint(30, 60))
                    fill_result["age"] = True
            except Exception:
                pass
        if not fill_result.get("age") and age_years is not None:
            excluded_indices = set()
            if name_entry and str(name_entry.get("visibleIndex", "")).isdigit():
                excluded_indices.add(int(name_entry.get("visibleIndex")))
            if _fill_second_visible_input([str(age_years)], excluded_visible_indices=excluded_indices):
                fill_result["age"] = True
        if len(date_parts) == 3 and _sync_hidden_birthday_input(page, f"{yyyy}-{mm}-{dd}", log):
            fill_result["birthdate"] = True
    elif about_mode == "birthday" or about_mode == "birthday_text":
        # First try segmented date input (MM / DD / YYYY DateField format)
        if len(date_parts) == 3 and _fill_segmented_date(mm, dd, yyyy):
            fill_result["birthdate"] = True
            log("about_you segmented date input succeeded")
        # Then try plain text input
        if not fill_result.get("birthdate"):
            for candidate in birthday_candidates:
                if _fill_locator(candidate, cn_birthdate):
                    fill_result["birthdate"] = True
                    break
                if _fill_locator(candidate, us_birthdate):
                    fill_result["birthdate"] = True
                    break
                if _fill_locator(candidate, birthdate):
                    fill_result["birthdate"] = True
                    break
                if _fill_locator(candidate, cn_birthdate.replace("/", "")):
                    fill_result["birthdate"] = True
                    break
                if _fill_locator(candidate, us_birthdate.replace("/", "")):
                    fill_result["birthdate"] = True
                    break
        if not fill_result.get("birthdate"):
            fallback_values = [cn_birthdate, cn_birthdate.replace("/", " / "), cn_birthdate.replace("/", ""), us_birthdate, us_birthdate.replace("/", " / "), us_birthdate.replace("/", ""), birthdate]
            if _fill_second_visible_input(fallback_values):
                fill_result["birthdate"] = True

    log(f"about_you fill result: {fill_result}")
    if not fill_result.get("name"):
        raise RuntimeError("about_you failed to fill Full name")
    if not (
        fill_result.get("birthdate")
        or fill_result.get("age")
        or (fill_result.get("month") and fill_result.get("day") and fill_result.get("year"))
    ):
        raise RuntimeError("about_you failed to fill Birthday/Age")
    _browser_pause(page)

    submit_selector = _click_first(
        page,
        [
            'button:has-text("Finish creating account")',
            'button:has-text("finish creating account")',
            'button[type="submit"]',
            'button[data-testid="continue-button"]',
            'button:has-text("Continue")',
            'button:has-text("continue")',
            'button:has-text("Next")',
            'button:has-text("next")',
        ],
        timeout=8,
    )
    if not submit_selector:
        raise RuntimeError("about_you submit button not found")
    log(f"about_you clicked continue button: {submit_selector}")

    deadline = time.time() + 20
    retried_generic_validation = False
    last_url = page.url
    while time.time() < deadline:
        current_url = page.url
        last_url = current_url or last_url
        if "code=" in current_url or "chatgpt.com" in current_url or "sign-in-with-chatgpt" in current_url:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        if "add-phone" in current_url:
            return {"ok": True, "status": 200, "url": current_url, "data": None, "text": ""}
        try:
            error_text = page.locator("text=Sorry, we cannot create your account").first.text_content(timeout=500)
        except Exception:
            error_text = ""
        if not error_text:
            try:
                error_text = page.locator("text=Enter a valid age to continue").first.text_content(timeout=300)
            except Exception:
                error_text = ""
        if not error_text:
            try:
                error_text = page.locator("text=doesn't look right").first.text_content(timeout=300)
            except Exception:
                error_text = ""
        if not error_text:
            try:
                error_text = page.locator("[role='alert']").first.text_content(timeout=300)
            except Exception:
                error_text = ""
        if not error_text:
            try:
                error_text = page.locator(".error, [class*='error'], [class*='Error']").first.text_content(timeout=300)
            except Exception:
                error_text = ""
        if error_text and "oai_log" not in error_text and "SSR_HTML" not in error_text:
            normalized_error = str(error_text).strip().lower()
            if (
                about_mode == "age"
                and not retried_generic_validation
                and ("doesn't look right" in normalized_error or "try again" in normalized_error)
            ):
                retried_generic_validation = True
                log("about_you age mode submit rejected, re-syncing Full name/Age/hidden birthday and retrying...")
                if direct_name_selector and _fill_input_like_user(page, direct_name_selector, name):
                    fill_result["name"] = True
                elif _fill_visible_input_entry(name_entry, name):
                    fill_result["name"] = True
                elif len(ordered_visible_entries) < 2:
                    for candidate in name_candidates:
                        if _fill_locator(candidate, name):
                            fill_result["name"] = True
                            break
                if age_years is not None:
                    if direct_age_selector and _fill_input_like_user(page, direct_age_selector, str(age_years)):
                        fill_result["age"] = True
                    elif _fill_visible_input_entry(age_entry, str(age_years)):
                        fill_result["age"] = True
                    elif len(ordered_visible_entries) < 2:
                        for candidate in age_candidates:
                            if _fill_locator(candidate, str(age_years)):
                                fill_result["age"] = True
                                break
                if len(date_parts) == 3 and _sync_hidden_birthday_input(page, f"{yyyy}-{mm}-{dd}", log):
                    fill_result["birthdate"] = True
                _browser_pause(page)
                retry_submit_selector = _click_first(
                    page,
                    [
                        'button:has-text("Finish creating account")',
                        'button:has-text("finish creating account")',
                        'button[type="submit"]',
                        'button[data-testid="continue-button"]',
                        'button:has-text("Continue")',
                        'button:has-text("continue")',
                        'button:has-text("Next")',
                        'button:has-text("next")',
                    ],
                    timeout=5,
                )
                if retry_submit_selector:
                    log(f"about_you retry submit button: {retry_submit_selector}")
                    time.sleep(0.5)
                    continue
            return {"ok": False, "status": 400, "url": current_url, "data": None, "text": error_text}
        time.sleep(0.5)
    _dump_debug(page, "chatgpt_about_you_fail")
    return {"ok": False, "status": 0, "url": last_url, "data": None, "text": "about_you submit did not redirect"}


def _browser_registration_flow(page, email: str, password: str, otp_callback, phone_callback, log) -> dict:
    device_id = str(uuid.uuid4())
    try:
        user_agent = str(page.evaluate("() => navigator.userAgent") or "").strip() or _random_chrome_ua()
    except Exception:
        user_agent = _random_chrome_ua()

    _seed_browser_device_id(page, device_id)
    try:
        state = _start_browser_signup_via_page(page, email, log)
    except Exception as exc:
        log(f"Page-driven registration entry failed, falling back to ChatGPT authorize entry: {exc}")
        state = _start_browser_signup_via_authorize(page, email, device_id, log)
    auth_cookies = _get_cookies(page)
    log(
        "Authorization cookies: "
        f"login_session={'yes' if auth_cookies.get('login_session') else 'no'}, "
        f"oai-did={'yes' if auth_cookies.get('oai-did') else 'no'}"
    )
    log(f"Registration state starting point: page={state.get('page_type') or '-'} url={(state.get('current_url') or '')[:100]}")
    register_submitted = False
    seen_states: dict[str, int] = {}

    for step in range(12):
        signature = "|".join(
            [
                str(state.get("page_type") or ""),
                str(state.get("method") or ""),
                str(state.get("continue_url") or ""),
                str(state.get("current_url") or ""),
            ]
        )
        seen_states[signature] = seen_states.get(signature, 0) + 1
        log(
            f"Registration state advancing: step={step+1} page={state.get('page_type') or '-'} "
            f"next={str(state.get('continue_url') or '')[:60]} seen={seen_states[signature]}"
        )
        if seen_states[signature] > 2:
            raise RuntimeError(f"Registration state stuck: page={state.get('page_type') or '-'}")

        if _is_registration_complete(state):
            _handle_post_signup_onboarding(page, log)
            return _extract_flow_state(None, page.url)

        if _is_password_registration(state):
            if register_submitted:
                raise RuntimeError("Re-entered password registration phase")
            log("Submitting registration password...")
            pre_cookies = _get_cookies(page)
            log(
                "Password phase cookies: "
                f"login_session={'yes' if pre_cookies.get('login_session') else 'no'}, "
                f"oai-client-auth-session={'yes' if pre_cookies.get('oai-client-auth-session') else 'no'}"
            )
            reg_resp = _submit_password_via_page(page, password, log)
            log(f"Password page submit status: {reg_resp.get('status', 0)}")
            if not reg_resp.get("ok"):
                raise RuntimeError(f"Password page submit failed: {(reg_resp.get('text') or '')[:300]}")
            register_submitted = True
            state = _extract_flow_state(reg_resp.get("data"), reg_resp.get("url", page.url))
            if not state.get("page_type") or _is_password_registration(state):
                state = _derive_registration_state_from_page(page)
            continue

        if str(state.get("page_type") or "") == "login_password":
            if _recover_signup_password_page(page, log):
                state = _derive_registration_state_from_page(page)
                continue
            log("Registration flow fell into existing account login password page, continuing with login authentication...")
            login_resp = _submit_oauth_password_direct(page, password, log)
            log(f"Login password page submit status: {login_resp.get('status', 0)}")
            if not login_resp.get("ok"):
                raise RuntimeError(f"Login password page submit failed: {(login_resp.get('text') or '')[:300]}")
            state = _extract_flow_state(login_resp.get("data"), login_resp.get("url", page.url))
            if not state.get("page_type"):
                state = _derive_registration_state_from_page(page)
            continue

        if _is_email_otp(state):
            if not otp_callback:
                raise RuntimeError("ChatGPT registration requires email verification code but no otp_callback provided")
            log("Waiting for ChatGPT verification code")
            code = otp_callback()
            if not code:
                raise RuntimeError("Failed to get verification code")
            otp_resp = _submit_otp_via_page(page, code, log)
            log(f"Verification code page submit status: {otp_resp.get('status', 0)}")
            if not otp_resp.get("ok"):
                raise RuntimeError(f"Verification code validation failed: {(otp_resp.get('text') or '')[:300]}")
            state = _extract_flow_state(otp_resp.get("data"), otp_resp.get("url", page.url))
            if not state.get("page_type"):
                state = _derive_registration_state_from_page(page)
            continue

        if _is_about_you(state):
            log("Submitting about_you info...")
            target_url = _normalize_url(
                str(state.get("current_url") or state.get("continue_url") or f"{OPENAI_AUTH}/about-you"),
                OPENAI_AUTH,
            )
            if "about-you" not in str(page.url):
                log(f"Navigating to about_you page: {target_url[:120]}")
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            about_resp = _submit_about_you_via_page(page, log)
            log(f"about_you submit status: {about_resp.get('status', 0)}")
            if not about_resp.get("ok"):
                raise RuntimeError(f"about_you submit failed: {(about_resp.get('text') or '')[:300]}")
            state = _extract_flow_state(about_resp.get("data"), about_resp.get("url", page.url))
            if not state.get("page_type"):
                state = _derive_registration_state_from_page(page)
            if _is_add_phone(state):
                if not phone_callback:
                    return state
                log("Entered add_phone after about_you, trying SMS verification...")
                state = _handle_add_phone_challenge(
                    page,
                    phone_callback,
                    device_id=device_id,
                    user_agent=user_agent,
                    log=log,
                    resume_url=f"{CHATGPT_APP}/",
                )
            continue

        if _is_add_phone(state):
            if not phone_callback:
                return state
            log("Registration flow entered add_phone, trying SMS verification...")
            state = _handle_add_phone_challenge(
                page,
                phone_callback,
                device_id=device_id,
                user_agent=user_agent,
                log=log,
                resume_url=f"{CHATGPT_APP}/",
            )
            continue

        if _requires_registration_navigation(state):
            target_url = _normalize_url(str(state.get("continue_url") or state.get("current_url") or ""), OPENAI_AUTH)
            if not target_url:
                raise RuntimeError("Missing followable continue_url")
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            state = _extract_flow_state(None, page.url)
            continue

        raise RuntimeError(f"Unsupported registration state: page={state.get('page_type') or '-'}")

    raise RuntimeError("Registration state machine exceeded maximum steps")


class ChatGPTBrowserRegister:
    def __init__(
        self,
        *,
        headless: bool,
        proxy: Optional[str] = None,
        otp_callback: Optional[Callable[[], str]] = None,
        phone_callback: Optional[Callable[[], str]] = None,
        log_fn: Callable[[str], None] = print,
    ):
        self.headless = headless
        self.proxy = proxy
        self.otp_callback = otp_callback
        self.phone_callback = phone_callback
        self.log = log_fn

    def run(self, email: str, password: str) -> dict:
        proxy = _build_proxy_config(self.proxy)
        launch_opts = {"headless": self.headless}
        if proxy:
            launch_opts["proxy"] = proxy
            launch_opts["geoip"] = True

        with Camoufox(**launch_opts) as browser:
            page = browser.new_page()
            self.log("Starting browser context registration state machine")
            final_state = _browser_registration_flow(
                page,
                email,
                password,
                self.otp_callback,
                self.phone_callback,
                self.log,
            )
            self.log(f"Registration flow completed: page={final_state.get('page_type') or '-'}")

            # Get session token and cookies
            cookies_dict = _get_cookies(page)

            # ═══ Get correct token via Codex CLI OAuth ═══
            # Do OAuth with clean browser context (registration cookies can interfere with OAuth flow)
            self.log("Executing Codex CLI OAuth flow to get token...")
            try:
                page.context.clear_cookies()
            except Exception:
                pass
            codex_result = _do_codex_oauth(
                page,
                cookies_dict,
                email,
                password,
                self.otp_callback,
                self.phone_callback,
                self.proxy,
                self.log,
            )
            cookies_dict = _get_cookies(page)
            session_token = cookies_dict.get("__Secure-next-auth.session-token", "")
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])

            if codex_result:
                self.log(f"Codex OAuth succeeded: account_id={codex_result.get('account_id','')}")
                self.log(f"Registration succeeded: {email}")
                return {
                    "email": email, "password": password,
                    "account_id": codex_result.get("account_id", ""),
                    "access_token": codex_result.get("access_token", ""),
                    "refresh_token": codex_result.get("refresh_token", ""),
                    "id_token": codex_result.get("id_token", ""),
                    "session_token": session_token,
                    "workspace_id": "", "cookies": cookie_str,
                    "profile": {},
                }

            self.log("Codex OAuth failed, trying fresh browser retry...")

        # Fresh browser OAuth retry (open new one outside with Camoufox)
        codex_result = self._retry_oauth_fresh_browser(email, password)
        if codex_result:
            self.log(f"Fresh browser OAuth succeeded: account_id={codex_result.get('account_id','')}")
            return {
                "email": email, "password": password,
                "account_id": codex_result.get("account_id", ""),
                "access_token": codex_result.get("access_token", ""),
                "refresh_token": codex_result.get("refresh_token", ""),
                "id_token": codex_result.get("id_token", ""),
                "session_token": "", "workspace_id": "",
                "cookies": "", "profile": {},
            }

        raise RuntimeError("ChatGPT registration did not complete full OAuth callback, refused to fall back to session/access_token partial results")

    def _retry_oauth_fresh_browser(self, email, password):
        """Do Codex OAuth in a fresh browser context (bypass add_phone session)."""
        proxy = _build_proxy_config(self.proxy)
        launch_opts = {"headless": self.headless}
        if proxy:
            launch_opts["proxy"] = proxy
        try:
            with Camoufox(**launch_opts) as browser:
                page = browser.new_page()
                self.log("  Fresh browser OAuth starting...")
                result = _do_codex_oauth(
                    page, {}, email, password,
                    self.otp_callback, self.phone_callback, self.proxy, self.log,
                )
                return result
        except Exception as e:
            self.log(f"  Fresh browser OAuth exception: {e}")
            return None
