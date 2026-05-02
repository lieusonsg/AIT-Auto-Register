"""
Registration flow engine
Extracted and refactored registration flow from main.py
"""

import re
import json
import time
import uuid
import base64
import random
import logging
import secrets
import string
from typing import Optional, Dict, Any, Tuple, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from curl_cffi import requests as cffi_requests

from .oauth import OAuthManager, OAuthStart, generate_oauth_url, submit_callback_url
from .http_client import OpenAIHTTPClient, HTTPClientError
# from ..services import EmailServiceFactory, BaseEmailService, EmailServiceType  # removed: external dep
# from ..database import crud  # removed: external dep
# from ..database.session import get_db  # removed: external dep
from .constants import (
    OPENAI_API_ENDPOINTS,
    OPENAI_PAGE_TYPES,
    generate_random_user_info,
    OTP_CODE_PATTERN,
    DEFAULT_PASSWORD_LENGTH,
    PASSWORD_CHARSET,
    AccountStatus,
    TaskStatus,
    SENTINEL_SDK_URL,
    OAUTH_REDIRECT_URI,
    OAUTH_CLIENT_ID,
)
# from ..config.settings import get_settings  # removed: external dep


logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    """Registration result"""
    success: bool
    email: str = ""
    password: str = ""  # Registration password
    account_id: str = ""
    workspace_id: str = ""
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    session_token: str = ""  # Session token
    error_message: str = ""
    logs: list = None
    metadata: dict = None
    source: str = "register"  # 'register' or 'login', distinguish account source

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict"""
        return {
            "success": self.success,
            "email": self.email,
            "password": self.password,
            "account_id": self.account_id,
            "workspace_id": self.workspace_id,
            "access_token": self.access_token[:20] + "..." if self.access_token else "",
            "refresh_token": self.refresh_token[:20] + "..." if self.refresh_token else "",
            "id_token": self.id_token[:20] + "..." if self.id_token else "",
            "session_token": self.session_token[:20] + "..." if self.session_token else "",
            "error_message": self.error_message,
            "logs": self.logs or [],
            "metadata": self.metadata or {},
            "source": self.source,
        }


@dataclass
class SignupFormResult:
    """Signup form submission result"""
    success: bool
    page_type: str = ""  # page.type field in response
    is_existing_account: bool = False  # Whether it's a registered account
    response_data: Dict[str, Any] = None  # Full response data
    error_message: str = ""


@dataclass
class SentinelPayload:
    """Sentinel request result."""
    p: str
    c: str
    flow: str
    t: str = ""


# ─── Sentinel helpers (ported from browser_register.py) ──────────

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


class _SentinelTokenGenerator:
    """Dynamic sentinel token generator – mirrors browser_register._SentinelTokenGenerator."""

    def __init__(self, device_id: str, user_agent: str):
        self.device_id = device_id or str(uuid.uuid4())
        self.user_agent = user_agent
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
            "webkitTemporaryStorage\u2212undefined",
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


class RegistrationEngine:
    """
    Registration engine
    Coordinates mailbox service, OAuth flow, and OpenAI API calls
    """

    def __init__(
        self,
        email_service: Any,
        proxy_url: Optional[str] = None,
        callback_logger: Optional[Callable[[str], None]] = None,
        task_uuid: Optional[str] = None
    ):
        """
        Initialize registration engine

        Args:
            email_service: Email service instance
            proxy_url: Proxy URL
            callback_logger: Log callback function
            task_uuid: Task UUID (for database records)
        """
        self.email_service = email_service
        self.proxy_url = proxy_url
        self.callback_logger = callback_logger or (lambda msg: logger.info(msg))
        self.task_uuid = task_uuid

        # Create HTTP client
        self.http_client = OpenAIHTTPClient(proxy_url=proxy_url)

        # Create OAuth manager
        from .constants import OAUTH_CLIENT_ID, OAUTH_AUTH_URL, OAUTH_TOKEN_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE
        self.oauth_manager = OAuthManager(
            client_id=OAUTH_CLIENT_ID,
            auth_url=OAUTH_AUTH_URL,
            token_url=OAUTH_TOKEN_URL,
            redirect_uri=OAUTH_REDIRECT_URI,
            scope=OAUTH_SCOPE,
            proxy_url=proxy_url  # Pass proxy configuration
        )

        # State variables
        self.email: Optional[str] = None
        self.password: Optional[str] = None  # Registration password
        self.email_info: Optional[Dict[str, Any]] = None
        self.oauth_start: Optional[OAuthStart] = None
        self.session: Optional[cffi_requests.Session] = None
        self.session_token: Optional[str] = None  # Session token
        self.logs: list = []
        self._otp_sent_at: Optional[float] = None  # OTP sent timestamp
        self._is_existing_account: bool = False  # Whether it's a registered account (for auto-login)
        self._device_id: Optional[str] = None
        self._sentinel_token: Optional[str] = None
        self._signup_sentinel: Optional[SentinelPayload] = None
        self._password_sentinel: Optional[SentinelPayload] = None
        self._create_account_continue_url: Optional[str] = None
        self._otp_continue_url: Optional[str] = None
        self._otp_page_type: Optional[str] = None

    def _log(self, message: str, level: str = "info"):
        """Log message"""
        timestamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"

        # Add to log list
        self.logs.append(log_message)

        # Call callback function
        if self.callback_logger:
            self.callback_logger(message)

        # Write to database (if associated task exists)
        if self.task_uuid:
            try:
                with get_db() as db:
                    crud.append_task_log(db, self.task_uuid, message)
            except Exception as e:
                logger.warning(f"Failed to log task event: {e}")

        # Log to logger by level
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

    def _generate_password(self, length: int = DEFAULT_PASSWORD_LENGTH) -> str:
        """Generate random password"""
        # OpenAI signup page rejects alphanumeric-only passwords more often, adding a symbol makes it more stable.
        specials = ",._!@#"
        if length < 10:
            length = 10
        core = ''.join(secrets.choice(PASSWORD_CHARSET) for _ in range(length - 2))
        return (
            secrets.choice("abcdefghijklmnopqrstuvwxyz")
            + secrets.choice("0123456789")
            + secrets.choice(specials)
            + core
        )[:length]

    def _load_create_account_password_page(self) -> bool:
        """Preload create-account/password page to get stage cookies."""
        try:
            response = self.session.get(
                "https://auth.openai.com/create-account/password",
                headers={
                    "referer": "https://chatgpt.com/",
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=20,
            )
            self._log(f"Load password page status: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            self._log(f"Failed to load password page: {e}", "warning")
            return False

    def _check_ip_location(self) -> Tuple[bool, Optional[str]]:
        """Check IP geolocation"""
        try:
            return self.http_client.check_ip_location()
        except Exception as e:
            self._log(f"Failed to check IP geolocation: {e}", "error")
            return False, None

    def _create_email(self) -> bool:
        """Create mailbox"""
        try:
            self._log(f"Creating {self.email_service.service_type.value} mailbox...")
            self.email_info = self.email_service.create_email()

            if not self.email_info or "email" not in self.email_info:
                self._log("Failed to create mailbox: incomplete response", "error")
                return False

            self.email = self.email_info["email"]
            self._log(f"Mailbox created successfully: {self.email}")
            return True

        except Exception as e:
            self._log(f"Failed to create mailbox: {e}", "error")
            return False

    def _start_oauth(self) -> bool:
        """Initiate OAuth flow via chatgpt.com NextAuth"""
        try:
            from .constants import CHATGPT_APP
            self._log("Initiating OAuth via chatgpt.com NextAuth...")

            # 1. Visit chatgpt.com to get base cookies
            self.session.get(f"{CHATGPT_APP}/", timeout=15)
            oai_did = self.session.cookies.get("oai-did", "")
            self._log(f"chatgpt.com oai-did: {oai_did[:20]}...")

            # 2. Get CSRF token
            csrf_resp = self.session.get(f"{CHATGPT_APP}/api/auth/csrf", timeout=15)
            csrf_data = csrf_resp.json()
            csrf_token = csrf_data.get("csrfToken", "")
            if not csrf_token:
                # Extract from cookies
                csrf_cookie = self.session.cookies.get("__Host-next-auth.csrf-token", "")
                csrf_token = csrf_cookie.split("%7C")[0] if "%7C" in csrf_cookie else csrf_cookie.split("|")[0]
            self._log(f"CSRF token: {csrf_token[:20]}...")

            # 3. Call signin/openai to get authorize URL
            signin_url = f"{CHATGPT_APP}/api/auth/signin/openai"
            if oai_did:
                signin_url += f"?prompt=login&ext-oai-did={oai_did}"

            signin_resp = self.session.post(
                signin_url,
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": CHATGPT_APP,
                    "referer": f"{CHATGPT_APP}/",
                },
                data=f"callbackUrl={CHATGPT_APP}%2F&csrfToken={csrf_token}&json=true",
                timeout=15,
            )
            self._log(f"signin/openai status: {signin_resp.status_code}")

            if signin_resp.status_code != 200:
                self._log(f"signin/openai failed: {signin_resp.text[:200]}", "error")
                return False

            signin_data = signin_resp.json()
            auth_url = signin_data.get("url", "")
            if not auth_url:
                self._log("signin/openai did not return authorize URL", "error")
                return False

            self._log(f"OAuth URL: {auth_url[:80]}...")

            # Store as OAuthStart (code_verifier not needed, handled by chatgpt.com backend)
            self.oauth_start = OAuthStart(
                auth_url=auth_url,
                state="",  # state managed by NextAuth
                code_verifier="",  # Not needed
                redirect_uri="",  # Not needed
            )
            return True

        except Exception as e:
            self._log(f"NextAuth OAuth flow failed: {e}", "error")
            return False

    def _init_session(self) -> bool:
        """Initialize session"""
        try:
            self.session = self.http_client.session
            return True
        except Exception as e:
            self._log(f"Failed to initialize session: {e}", "error")
            return False

    def _get_device_id(self) -> Optional[str]:
        """Get Device ID"""
        try:
            if not self.oauth_start:
                return None

            response = self.session.get(
                self.oauth_start.auth_url,
                timeout=15
            )
            did = self.session.cookies.get("oai-did")
            self._log(f"Device ID: {did}")
            return did

        except Exception as e:
            self._log(f"Failed to get Device ID: {e}", "error")
            return None

    def _check_sentinel(self, did: str, *, flow: str = "authorize_continue") -> Optional[SentinelPayload]:
        """Check Sentinel interception (dynamic token generation + PoW handling)"""
        try:
            ua = self.http_client.default_headers.get("User-Agent", "")
            generator = _SentinelTokenGenerator(did, ua)
            sent_p = generator.generate_requirements_token()
            sen_req_body = json.dumps({"p": sent_p, "id": did, "flow": flow}, separators=(",", ":"))

            from .constants import SENTINEL_FRAME_URL
            response = self.http_client.post(
                OPENAI_API_ENDPOINTS["sentinel"],
                headers={
                    "origin": "https://sentinel.openai.com",
                    "referer": SENTINEL_FRAME_URL,
                    "content-type": "text/plain;charset=UTF-8",
                },
                data=sen_req_body,
            )

            if response.status_code == 200:
                data = response.json()
                sen_token = str(data.get("token") or "")
                turnstile = data.get("turnstile") or {}

                # Handle proofofwork challenge if required
                initial_p = sent_p  # keep for dx decryption
                pow_meta = data.get("proofofwork") or {}
                if pow_meta.get("required") and pow_meta.get("seed"):
                    sent_p = generator.generate_token(
                        str(pow_meta.get("seed") or ""),
                        str(pow_meta.get("difficulty") or "0"),
                    )
                    self._log(f"Sentinel PoW solved: flow={flow}")

                # Solve turnstile dx with VM
                t_value = ""
                dx_b64 = str(turnstile.get("dx") or "")
                if dx_b64:
                    try:
                        from .sentinel_vm import solve_turnstile_dx
                        from .constants import SENTINEL_SDK_URL
                        t_value = solve_turnstile_dx(dx_b64, initial_p, user_agent=ua, sdk_url=SENTINEL_SDK_URL)
                        self._log(f"Sentinel VM solved: t_len={len(t_value)} flow={flow}")
                    except Exception as vm_err:
                        self._log(f"Sentinel VM failed: {vm_err}", "warning")

                payload = SentinelPayload(
                    p=sent_p,
                    c=sen_token,
                    flow=flow,
                    t=t_value,
                )
                self._log(f"Sentinel token obtained successfully: flow={flow}")
                return payload
            else:
                self._log(f"Sentinel check failed: flow={flow} status={response.status_code}", "warning")
                return None

        except Exception as e:
            self._log(f"Sentinel check exception: flow={flow} {e}", "warning")
            return None

    def _submit_signup_form(self, did: str, sen_payload: Optional[SentinelPayload]) -> SignupFormResult:
        """
        Submit signup form (establish session via authorize/continue)

        Returns:
            SignupFormResult: Submission result with account status determination
        """
        try:
            self._device_id = did
            self._signup_sentinel = sen_payload
            self._sentinel_token = sen_payload.c if sen_payload else None
            signup_body = f'{{"username":{{"value":"{self.email}","kind":"email"}},"screen_hint":"signup"}}'

            headers = {
                "referer": "https://auth.openai.com/create-account",
                "accept": "application/json",
                "content-type": "application/json",
            }

            if sen_payload:
                sentinel = json.dumps({
                    "p": sen_payload.p,
                    "t": sen_payload.t,
                    "c": sen_payload.c,
                    "id": did,
                    "flow": sen_payload.flow,
                }, separators=(",", ":"))
                headers["openai-sentinel-token"] = sentinel

            response = self.session.post(
                OPENAI_API_ENDPOINTS["signup"],
                headers=headers,
                data=signup_body,
            )

            self._log(f"Signup form submission status: {response.status_code}")

            if response.status_code != 200:
                return SignupFormResult(
                    success=False,
                    error_message=f"HTTP {response.status_code}: {response.text[:200]}"
                )

            try:
                response_data = response.json()
                page_type = response_data.get("page", {}).get("type", "")
                self._log(f"Response page type: {page_type}")

                is_existing = page_type == OPENAI_PAGE_TYPES["EMAIL_OTP_VERIFICATION"]
                if is_existing:
                    self._log("Detected registered account, switching to login flow")
                    self._is_existing_account = True

                return SignupFormResult(
                    success=True,
                    page_type=page_type,
                    is_existing_account=is_existing,
                    response_data=response_data
                )

            except Exception as parse_error:
                self._log(f"Failed to parse response: {parse_error}", "warning")
                return SignupFormResult(success=True)

        except Exception as e:
            self._log(f"Failed to submit signup form: {e}", "error")
            return SignupFormResult(success=False, error_message=str(e))

    def _register_password(self) -> Tuple[bool, Optional[str]]:
        """Set registration password"""
        try:
            ua = self.http_client.default_headers.get("User-Agent", "")
            chrome_match = re.search(r"Chrome/(\d+)", ua)
            chrome_major = str(chrome_match.group(1) if chrome_match else "136")
            sec_ch_ua = f'"Chromium";v="{chrome_major}", "Google Chrome";v="{chrome_major}", "Not.A/Brand";v="99"'

            candidates = []
            while len(candidates) < 3:
                pwd = self._generate_password()
                if pwd not in candidates:
                    candidates.append(pwd)

            for index, password in enumerate(candidates, start=1):
                self.password = password

                # Reload page + refresh sentinel for each attempt (tokens are single-use)
                self._load_create_account_password_page()
                if self._device_id:
                    self._password_sentinel = self._check_sentinel(self._device_id, flow="username_password_create")
                    if self._password_sentinel:
                        self._log(
                            f"Password stage Sentinel refreshed: flow={self._password_sentinel.flow} "
                            f"turnstile={'yes' if self._password_sentinel.t else 'no'}"
                        )

                self._log(f"Generating password[{index}/{len(candidates)}]: {password}")

                register_body = json.dumps({
                    "password": password,
                    "username": self.email
                })

                register_headers = {
                    "origin": "https://auth.openai.com",
                    "referer": "https://auth.openai.com/create-account/password",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "accept-language": "en-US,en;q=0.9",
                    "sec-ch-ua": sec_ch_ua,
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                    **_generate_datadog_trace_headers(),
                }
                if self._device_id:
                    register_headers["oai-device-id"] = self._device_id
                if self._password_sentinel and self._device_id:
                    register_headers["openai-sentinel-token"] = json.dumps({
                        "p": self._password_sentinel.p,
                        "t": self._password_sentinel.t,
                        "c": self._password_sentinel.c,
                        "id": self._device_id,
                        "flow": self._password_sentinel.flow,
                    }, separators=(",", ":"))

                response = self.session.post(
                    OPENAI_API_ENDPOINTS["register"],
                    headers=register_headers,
                    data=register_body,
                )

                self._log(f"Password submission status[{index}/{len(candidates)}]: {response.status_code}")

                if response.status_code == 200:
                    # Parse response, detect registered account
                    try:
                        resp_data = response.json()
                        page_type = resp_data.get("page", {}).get("type", "")
                        self._log(f"Registration response page type: {page_type}")
                        if page_type == OPENAI_PAGE_TYPES.get("EMAIL_OTP_VERIFICATION", "email_otp_verification"):
                            self._log("Detected registered account, auto-switching to login flow")
                            self._is_existing_account = True
                    except Exception:
                        pass
                    return True, password

                error_text = response.text[:500]
                self._log(f"Password registration failed[{index}/{len(candidates)}]: {error_text}", "warning")

                try:
                    error_json = response.json()
                    error_msg = error_json.get("error", {}).get("message", "")
                    error_code = error_json.get("error", {}).get("code", "")

                    if "already" in error_msg.lower() or "exists" in error_msg.lower() or error_code == "user_exists":
                        self._log(f"Email {self.email} may already be registered with OpenAI", "error")
                        self._mark_email_as_registered()
                        return False, None
                except Exception:
                    pass

            return False, None

        except Exception as e:
            self._log(f"Password registration failed: {e}", "error")
            return False, None

    def _mark_email_as_registered(self):
        """Mark email as registered (to prevent repeated attempts)"""
        try:
            with get_db() as db:
                # Check if record for this email already exists
                existing = crud.get_account_by_email(db, self.email)
                if not existing:
                    # Create a failed record marking the email as registered
                    crud.create_account(
                        db,
                        email=self.email,
                        password="",  # Empty password indicates registration did not succeed
                        email_service=self.email_service.service_type.value,
                        email_service_id=self.email_info.get("service_id") if self.email_info else None,
                        status="failed",
                        extra_data={"register_failed_reason": "email_already_registered_on_openai"}
                    )
                    self._log(f"Email {self.email} marked as registered in database")
        except Exception as e:
            logger.warning(f"Failed to mark email status: {e}")

    def _send_verification_code(self) -> bool:
        """Send verification code"""
        try:
            # Record send timestamp
            self._otp_sent_at = time.time()

            response = self.session.get(
                OPENAI_API_ENDPOINTS["send_otp"],
                headers={
                    "referer": "https://auth.openai.com/create-account/password",
                    "accept": "application/json",
                },
            )

            self._log(f"Verification code send status: {response.status_code}")
            return response.status_code == 200

        except Exception as e:
            self._log(f"Failed to send verification code: {e}", "error")
            return False

    def _get_verification_code(self) -> Optional[str]:
        """Get verification code"""
        try:
            self._log(f"Waiting for verification code for mailbox {self.email}...")

            email_id = self.email_info.get("service_id") if self.email_info else None
            code = self.email_service.get_verification_code(
                email=self.email,
                email_id=email_id,
                timeout=120,
                pattern=OTP_CODE_PATTERN,
                otp_sent_at=self._otp_sent_at,
            )

            if code:
                self._log(f"Verification code obtained successfully: {code}")
                return code
            else:
                self._log("Timed out waiting for verification code", "error")
                return None

        except Exception as e:
            self._log(f"Failed to get verification code: {e}", "error")
            return None

    def _validate_verification_code(self, code: str) -> bool:
        """Verify verification code"""
        try:
            code_body = f'{{"code":"{code}"}}'

            response = self.session.post(
                OPENAI_API_ENDPOINTS["validate_otp"],
                headers={
                    "referer": "https://auth.openai.com/email-verification",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=code_body,
            )

            self._log(f"Verification code check status: {response.status_code}")
            if response.status_code != 200:
                self._log(f"Verification code check response: {response.text[:300]}", "warning")
                return False

            # Parse response, store continue_url and page_type
            try:
                resp_data = response.json()
                self._otp_continue_url = resp_data.get("continue_url", "")
                self._otp_page_type = resp_data.get("page", {}).get("type", "")
                self._log(f"Verification code check -> page_type={self._otp_page_type}")
            except Exception:
                self._otp_continue_url = ""
                self._otp_page_type = ""
            return True

        except Exception as e:
            self._log(f"Failed to verify verification code: {e}", "error")
            return False

    def _create_user_account(self) -> bool:
        """Create user account"""
        try:
            user_info = generate_random_user_info()
            self._log(f"Generating user info: {user_info['name']}, birthday: {user_info['birthdate']}")
            create_account_body = json.dumps(user_info)

            # Call client_auth_session_dump to advance server auth state machine
            try:
                dump_resp = self.session.get(
                    "https://auth.openai.com/api/accounts/client_auth_session_dump",
                    headers={
                        "referer": "https://auth.openai.com/email-verification",
                        "accept": "application/json",
                    },
                    timeout=20,
                )
                self._log(f"client_auth_session_dump status: {dump_resp.status_code}")
            except Exception as e:
                self._log(f"client_auth_session_dump exception: {e}", "warning")

            create_headers = {
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
                "origin": "https://auth.openai.com",
                "sec-fetch-site": "same-origin",
                **_generate_datadog_trace_headers(),
            }
            if self._device_id:
                create_headers["oai-device-id"] = self._device_id

            # create_account also needs sentinel token (flow=oauth_create_account)
            if self._device_id:
                ca_sentinel = self._check_sentinel(self._device_id, flow="oauth_create_account")
                if ca_sentinel:
                    create_headers["openai-sentinel-token"] = json.dumps({
                        "p": ca_sentinel.p,
                        "t": ca_sentinel.t,
                        "c": ca_sentinel.c,
                        "id": self._device_id,
                        "flow": ca_sentinel.flow,
                    }, separators=(",", ":"))
                    self._log(f"create_account Sentinel obtained: flow={ca_sentinel.flow}")

            response = self.session.post(
                OPENAI_API_ENDPOINTS["create_account"],
                headers=create_headers,
                data=create_account_body,
            )

            self._log(f"Account creation status: {response.status_code}")

            if response.status_code != 200:
                self._log(f"Account creation failed: {response.text[:200]}", "warning")
                return False

            # Extract continue_url (ChatGPT Web flow directly returns OAuth callback URL)
            try:
                resp_data = response.json()
                self._create_account_continue_url = resp_data.get("continue_url", "")
                if self._create_account_continue_url:
                    self._log(f"create_account continue_url: {self._create_account_continue_url[:100]}...")
            except Exception:
                pass

            return True

        except Exception as e:
            self._log(f"Failed to create account: {e}", "error")
            return False

    def _acquire_codex_callback(self) -> Optional[str]:
        """
        After registration, get callback URL via Codex CLI OAuth login flow.
        Use new session, go through authorize -> authorize/continue -> OTP -> callback flow.
        """
        try:
            from .constants import (
                CODEX_CLIENT_ID, CODEX_REDIRECT_URI, CODEX_SCOPE,
                OPENAI_AUTH, OPENAI_API_ENDPOINTS,
            )
            import urllib.parse

            self._log("Starting Codex CLI login flow...")

            # 1. Create new HTTP client + session
            login_client = OpenAIHTTPClient(proxy_url=self.proxy_url)
            login_session = login_client.session

            # 2. Generate Codex CLI OAuth URL (Hydra)
            codex_oauth = generate_oauth_url(
                redirect_uri=CODEX_REDIRECT_URI,
                scope=CODEX_SCOPE,
                client_id=CODEX_CLIENT_ID,
            )
            self._codex_oauth = codex_oauth

            # 3. Visit authorize URL to get device_id + session cookies
            response = login_session.get(codex_oauth.auth_url, timeout=15)
            did = login_session.cookies.get("oai-did")
            self._log(f"Codex login device_id: {did}")
            if not did:
                self._log("Codex login failed to get device_id", "error")
                return None

            # 4. Get Sentinel token
            sen_payload = None
            try:
                ua = login_client.default_headers.get("User-Agent", "")
                generator = _SentinelTokenGenerator(did, ua)
                sent_p = generator.generate_requirements_token()
                sen_req_body = json.dumps({"p": sent_p, "id": did, "flow": "authorize_continue"}, separators=(",", ":"))

                from .constants import SENTINEL_FRAME_URL
                sen_resp = login_client.post(
                    OPENAI_API_ENDPOINTS["sentinel"],
                    headers={
                        "origin": "https://sentinel.openai.com",
                        "referer": SENTINEL_FRAME_URL,
                        "content-type": "text/plain;charset=UTF-8",
                    },
                    data=sen_req_body,
                )
                if sen_resp.status_code == 200:
                    data = sen_resp.json()
                    turnstile = data.get("turnstile") or {}
                    pow_meta = data.get("proofofwork") or {}
                    if pow_meta.get("required") and pow_meta.get("seed"):
                        sent_p = generator.generate_token(
                            str(pow_meta.get("seed") or ""),
                            str(pow_meta.get("difficulty") or "0"),
                        )
                    t_raw = turnstile.get("dx", "")
                    t_val = ""
                    if t_raw:
                        try:
                            t_val = generator.decrypt_turnstile(t_raw, sent_p)
                        except Exception:
                            pass
                    sen_payload = SentinelPayload(p=sent_p, t=t_val, c=str(data.get("token") or ""), flow="authorize_continue")
                    self._log("Codex login Sentinel obtained")
            except Exception as e:
                self._log(f"Codex login Sentinel failed: {e}", "warning")

            # 5. authorize/continue submit email (login to existing account)
            signup_body = f'{{"username":{{"value":"{self.email}","kind":"email"}},"screen_hint":"login"}}'
            headers = {
                "referer": "https://auth.openai.com/log-in",
                "accept": "application/json",
                "content-type": "application/json",
            }
            if sen_payload:
                headers["openai-sentinel-token"] = json.dumps({
                    "p": sen_payload.p, "t": sen_payload.t, "c": sen_payload.c,
                    "id": did, "flow": sen_payload.flow,
                }, separators=(",", ":"))

            resp = login_session.post(OPENAI_API_ENDPOINTS["signup"], headers=headers, data=signup_body)
            self._log(f"Codex login authorize/continue: {resp.status_code}")
            if resp.status_code != 200:
                self._log(f"Codex login authorize/continue failed: {resp.text[:200]}", "error")
                return None

            resp_data = resp.json()
            page_type = resp_data.get("page", {}).get("type", "")
            self._log(f"Codex login page_type: {page_type}")

            # 6. If OTP needed, wait for second verification code
            if page_type == "email_otp_verification":
                self._log("Waiting for second verification code...")
                self._otp_sent_at = time.time()
                code = self._get_verification_code()
                if not code:
                    self._log("Codex login failed to get verification code", "error")
                    return None

                # Verify OTP
                code_body = f'{{"code":"{code}"}}'
                otp_resp = login_session.post(
                    OPENAI_API_ENDPOINTS["validate_otp"],
                    headers={
                        "referer": "https://auth.openai.com/email-verification",
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    data=code_body,
                )
                self._log(f"Codex login OTP verification: {otp_resp.status_code}")
                if otp_resp.status_code != 200:
                    self._log(f"Codex login OTP failed: {otp_resp.text[:200]}", "error")
                    return None

                otp_data = otp_resp.json()
                otp_page = otp_data.get("page", {}).get("type", "")
                self._log(f"Codex login OTP -> page_type={otp_page}")

                if otp_page == "add_phone":
                    self._log("Codex CLI login still requires add_phone, cannot skip", "error")
                    return None

            # 7. Password login required
            elif page_type in ("login_password", "create_account_password"):
                self._log("Codex login submitting password...")
                if not self.password:
                    self._log("No password available", "error")
                    return None

                # Load password page to get sentinel
                login_session.get(f"{OPENAI_AUTH}/log-in/password", timeout=15)
                pwd_sentinel = None
                try:
                    ua2 = login_client.default_headers.get("User-Agent", "")
                    gen2 = _SentinelTokenGenerator(did, ua2)
                    sp2 = gen2.generate_requirements_token()
                    sr2 = json.dumps({"p": sp2, "id": did, "flow": "login_password"}, separators=(",", ":"))
                    from .constants import SENTINEL_FRAME_URL as SF2
                    sr2_resp = login_client.post(
                        OPENAI_API_ENDPOINTS["sentinel"],
                        headers={"origin": "https://sentinel.openai.com", "referer": SF2, "content-type": "text/plain;charset=UTF-8"},
                        data=sr2,
                    )
                    if sr2_resp.status_code == 200:
                        d2 = sr2_resp.json()
                        pm2 = d2.get("proofofwork") or {}
                        if pm2.get("required") and pm2.get("seed"):
                            sp2 = gen2.generate_token(str(pm2.get("seed") or ""), str(pm2.get("difficulty") or "0"))
                        tr2 = (d2.get("turnstile") or {}).get("dx", "")
                        tv2 = ""
                        if tr2:
                            try: tv2 = gen2.decrypt_turnstile(tr2, sp2)
                            except: pass
                        pwd_sentinel = SentinelPayload(p=sp2, t=tv2, c=str(d2.get("token") or ""), flow="login_password")
                        self._log("Codex login password Sentinel obtained")
                except Exception as e:
                    self._log(f"Codex login password Sentinel failed: {e}", "warning")

                pwd_headers = {
                    "origin": OPENAI_AUTH,
                    "referer": f"{OPENAI_AUTH}/log-in/password",
                    "accept": "application/json",
                    "content-type": "application/json",
                }
                if did:
                    pwd_headers["oai-device-id"] = did
                if pwd_sentinel:
                    pwd_headers["openai-sentinel-token"] = json.dumps({
                        "p": pwd_sentinel.p, "t": pwd_sentinel.t, "c": pwd_sentinel.c,
                        "id": did, "flow": pwd_sentinel.flow,
                    }, separators=(",", ":"))

                pwd_body = json.dumps({"password": self.password, "username": self.email})
                pwd_resp = login_session.post(OPENAI_API_ENDPOINTS["register"], headers=pwd_headers, data=pwd_body)
                self._log(f"Codex login password submitted: {pwd_resp.status_code}")
                if pwd_resp.status_code != 200:
                    self._log(f"Codex login password failed: {pwd_resp.text[:200]}", "error")
                    return None

                pwd_data = pwd_resp.json()
                pwd_page = pwd_data.get("page", {}).get("type", "")
                self._log(f"Codex login password -> page_type={pwd_page}")

                # OTP may be needed after password
                if pwd_page == "email_otp_verification" or pwd_page == "email_otp_send":
                    if pwd_page == "email_otp_send":
                        login_session.get(OPENAI_API_ENDPOINTS["send_otp"], headers={
                            "referer": f"{OPENAI_AUTH}/email-verification",
                        }, timeout=15)
                    self._log("Codex login: waiting for verification code...")
                    self._otp_sent_at = time.time()
                    code = self._get_verification_code()
                    if not code:
                        self._log("Codex login failed to get verification code", "error")
                        return None
                    code_body = f'{{"code":"{code}"}}'
                    otp_resp = login_session.post(
                        OPENAI_API_ENDPOINTS["validate_otp"],
                        headers={"referer": f"{OPENAI_AUTH}/email-verification", "accept": "application/json", "content-type": "application/json"},
                        data=code_body,
                    )
                    self._log(f"Codex login OTP: {otp_resp.status_code}")
                    if otp_resp.status_code != 200:
                        self._log(f"Codex login OTP failed: {otp_resp.text[:200]}", "error")
                        return None
                    otp_data = otp_resp.json()
                    otp_page = otp_data.get("page", {}).get("type", "")
                    self._log(f"Codex login OTP -> page_type={otp_page}")
                    if otp_page == "add_phone":
                        self._log("Codex CLI login still requires add_phone", "error")
                        return None

            # 8. Re-visit authorize URL to get callback
            self._log("Codex login: re-visiting OAuth URL to get callback...")
            response = login_session.get(codex_oauth.auth_url, allow_redirects=False, timeout=15)
            max_redirects = 10
            current_url = codex_oauth.auth_url
            for i in range(max_redirects):
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                location = response.headers.get("Location", "")
                if not location:
                    break
                next_url = urllib.parse.urljoin(current_url, location)
                self._log(f"Codex login redirect {i+1}: {next_url[:80]}...")
                if "code=" in next_url and "state=" in next_url:
                    self._log("Found Codex CLI callback URL")
                    return next_url
                current_url = next_url
                response = login_session.get(current_url, allow_redirects=False, timeout=15)

            self._log(f"Codex login final: status={response.status_code}, url={current_url[:100]}", "warning")
            return None

        except Exception as e:
            self._log(f"Codex CLI login flow failed: {e}", "error")
            return None

    def _get_workspace_id(self) -> Optional[str]:
        """Get Workspace ID"""
        try:
            auth_cookie = self.session.cookies.get("oai-client-auth-session")
            if not auth_cookie:
                self._log("Failed to get authorization cookie", "error")
                return None

            # Decode JWT
            import base64
            import json as json_module

            try:
                segments = auth_cookie.split(".")
                if len(segments) < 1:
                    self._log("Authorization cookie format error", "error")
                    return None

                # Decode first segment
                payload = segments[0]
                pad = "=" * ((4 - (len(payload) % 4)) % 4)
                decoded = base64.urlsafe_b64decode((payload + pad).encode("ascii"))
                auth_json = json_module.loads(decoded.decode("utf-8"))

                workspaces = auth_json.get("workspaces") or []
                if not workspaces:
                    self._log("Authorization cookie has no workspace info", "error")
                    return None

                workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
                if not workspace_id:
                    self._log("Cannot parse workspace_id", "error")
                    return None

                self._log(f"Workspace ID: {workspace_id}")
                return workspace_id

            except Exception as e:
                self._log(f"Failed to parse authorization cookie: {e}", "error")
                return None

        except Exception as e:
            self._log(f"Failed to get Workspace ID: {e}", "error")
            return None

    def _select_workspace(self, workspace_id: str) -> Optional[str]:
        """Select Workspace"""
        try:
            select_body = f'{{"workspace_id":"{workspace_id}"}}'

            response = self.session.post(
                OPENAI_API_ENDPOINTS["select_workspace"],
                headers={
                    "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                    "content-type": "application/json",
                },
                data=select_body,
            )

            if response.status_code != 200:
                self._log(f"Failed to select workspace: {response.status_code}", "error")
                self._log(f"Response: {response.text[:200]}", "warning")
                return None

            continue_url = str((response.json() or {}).get("continue_url") or "").strip()
            if not continue_url:
                self._log("workspace/select response missing continue_url", "error")
                return None

            self._log(f"Continue URL: {continue_url[:100]}...")
            return continue_url

        except Exception as e:
            self._log(f"Failed to select workspace: {e}", "error")
            return None

    def _follow_redirects(self, start_url: str) -> Optional[str]:
        """Follow redirect chain, find callback URL"""
        try:
            current_url = start_url
            max_redirects = 6

            for i in range(max_redirects):
                self._log(f"Redirect {i+1}/{max_redirects}: {current_url[:100]}...")

                response = self.session.get(
                    current_url,
                    allow_redirects=False,
                    timeout=15
                )

                location = response.headers.get("Location") or ""

                # Stop if not a redirect status code
                if response.status_code not in [301, 302, 303, 307, 308]:
                    self._log(f"Non-redirect status code: {response.status_code}")
                    break

                if not location:
                    self._log("Redirect response missing Location header")
                    break

                # Build next URL
                import urllib.parse
                next_url = urllib.parse.urljoin(current_url, location)

                # Check if callback parameters are included
                if "code=" in next_url and "state=" in next_url:
                    self._log(f"Found callback URL: {next_url[:100]}...")
                    return next_url

                current_url = next_url

            self._log("Failed to find callback URL in redirect chain", "error")
            return None

        except Exception as e:
            self._log(f"Failed to follow redirects: {e}", "error")
            return None

    def _handle_oauth_callback(self, callback_url: str) -> Optional[Dict[str, Any]]:
        """Handle OAuth callback"""
        try:
            if not self.oauth_start:
                self._log("OAuth flow not initialized", "error")
                return None

            self._log("Handling OAuth callback...")
            token_info = self.oauth_manager.handle_callback(
                callback_url=callback_url,
                expected_state=self.oauth_start.state,
                code_verifier=self.oauth_start.code_verifier
            )

            self._log("OAuth authorization succeeded")
            return token_info

        except Exception as e:
            self._log(f"Failed to handle OAuth callback: {e}", "error")
            return None

    def run(self) -> RegistrationResult:
        """
        Execute the full registration flow

        Supports automatic login for already-registered accounts:
        - If email is detected as already registered, automatically switch to login flow
        - Already-registered accounts skip: set password, send verification code, create user account
        - Shared steps: get verification code, validate verification code, Workspace and OAuth callback

        Returns:
            RegistrationResult: Registration result
        """
        result = RegistrationResult(success=False, logs=self.logs)

        try:
            self._log("=" * 60)
            self._log("Starting registration flow")
            self._log("=" * 60)

            # 1. Check IP geolocation
            self._log("1. Checking IP geolocation...")
            ip_ok, location = self._check_ip_location()
            if not ip_ok:
                result.error_message = f"IP geolocation not supported: {location}"
                self._log(f"IP check failed: {location}", "error")
                return result

            self._log(f"IP location: {location}")

            # 2. Create email
            self._log("2. Creating email...")
            if not self._create_email():
                result.error_message = "Failed to create email"
                return result

            result.email = self.email

            # 3. Initialize session
            self._log("3. Initializing session...")
            if not self._init_session():
                result.error_message = "Failed to initialize session"
                return result

            # 4. Start OAuth flow
            self._log("4. Starting OAuth authorization flow...")
            if not self._start_oauth():
                result.error_message = "Failed to start OAuth flow"
                return result

            # 5. Get Device ID
            self._log("5. Getting Device ID...")
            did = self._get_device_id()
            if not did:
                result.error_message = "Failed to get Device ID"
                return result

            # 6. Check Sentinel interception
            self._log("6. Checking Sentinel interception...")
            sen_payload = self._check_sentinel(did)
            if sen_payload:
                self._log("Sentinel check passed")
            else:
                self._log("Sentinel check failed or not enabled", "warning")

            # 7. Submit registration form + parse response to determine account status
            self._log("7. Submitting registration form...")
            signup_result = self._submit_signup_form(did, sen_payload)
            if not signup_result.success:
                result.error_message = f"Failed to submit registration form: {signup_result.error_message}"
                return result

            # 8. [Skip for existing accounts] Register password
            if self._is_existing_account:
                self._log("8. [Existing account] Skipping password setup, OTP auto-sent")
            else:
                self._log("8. Registering password...")
                password_ok, password = self._register_password()
                if not password_ok:
                    result.error_message = "Failed to register password"
                    return result

            # 9. [Skip for existing accounts] Send verification code
            if self._is_existing_account:
                self._log("9. [Existing account] Skipping send verification code, using auto-sent OTP")
                # Existing account OTP was auto-sent when submitting form, record timestamp
                self._otp_sent_at = time.time()
            else:
                self._log("9. Sending verification code...")
                if not self._send_verification_code():
                    result.error_message = "Failed to send verification code"
                    return result

            # 10. Get verification code
            self._log("10. Waiting for verification code...")
            code = self._get_verification_code()
            if not code:
                result.error_message = "Failed to get verification code"
                return result

            # 11. Validate verification code
            self._log("11. Validating verification code...")
            if not self._validate_verification_code(code):
                result.error_message = "Failed to validate verification code"
                return result

            # 12. Decide next step based on OTP response
            if self._otp_page_type == "about_you" and not self._is_existing_account:
                # Normal registration flow: about_you -> create_account
                self._log("12. Creating user account...")
                if not self._create_user_account():
                    result.error_message = "Failed to create user account"
                    return result
            elif self._is_existing_account:
                self._log("12. [Existing account] Skipping user account creation")
            else:
                self._log(f"12. OTP page_type={self._otp_page_type}, trying to create account...")
                if not self._create_user_account():
                    result.error_message = "Failed to create user account"
                    return result

            # 13. Follow callback URL to chatgpt.com to get session
            callback_url = self._create_account_continue_url
            if not callback_url or "code=" not in str(callback_url):
                result.error_message = "create_account did not return a valid callback URL"
                return result

            self._log("13. Following callback URL to chatgpt.com...")
            cb_resp = self.session.get(callback_url, timeout=20)
            self._log(f"Callback status: {cb_resp.status_code}")

            # Extract session cookie
            session_token = self.session.cookies.get("__Secure-next-auth.session-token")
            account_cookie = self.session.cookies.get("_account", "")
            if session_token:
                self._log(f"Got session-token: {session_token[:30]}...")
            if account_cookie:
                self._log(f"Got _account: {account_cookie}")

            # 14. Get access_token from chatgpt.com/api/auth/session
            from .constants import CHATGPT_APP
            self._log("14. Getting session info...")
            session_resp = self.session.get(
                f"{CHATGPT_APP}/api/auth/session",
                headers={"accept": "application/json"},
                timeout=15,
            )
            self._log(f"Session API status: {session_resp.status_code}")
            self._log(f"Session API response: {session_resp.text[:500]}")

            session_data = session_resp.json()
            access_token = session_data.get("accessToken", "")
            user_data = session_data.get("user", {})
            self._log(f"session keys: {list(session_data.keys())}")
            self._log(f"accessToken length: {len(access_token)}")

            if not access_token:
                result.error_message = "chatgpt.com session did not return accessToken"
                return result

            self._log("NextAuth session obtained successfully")

            # 15. Codex CLI OTP login to get refresh_token + id_token
            codex_token_info = None
            try:
                self._log("15. Codex CLI OTP login...")
                from .constants import (
                    CODEX_CLIENT_ID, CODEX_REDIRECT_URI, CODEX_SCOPE,
                    OPENAI_AUTH, SENTINEL_FRAME_URL,
                )
                import urllib.parse

                codex_oauth = generate_oauth_url(
                    redirect_uri=CODEX_REDIRECT_URI,
                    scope=CODEX_SCOPE,
                    client_id=CODEX_CLIENT_ID,
                )

                # Use a fresh session (Hydra needs a clean session)
                login_client = OpenAIHTTPClient(proxy_url=self.proxy_url)
                login_session = login_client.session

                # Visit Codex OAuth URL, follow redirects to /log-in
                login_session.get(codex_oauth.auth_url, timeout=15)
                did2 = login_session.cookies.get("oai-did", "")
                self._log(f"Codex login did: {did2[:20]}...")

                # Get sentinel (using login_client)
                sen2 = None
                try:
                    ua2 = login_client.default_headers.get("User-Agent", "")
                    gen2 = _SentinelTokenGenerator(did2, ua2)
                    sp2 = gen2.generate_requirements_token()
                    sr2 = json.dumps({"p": sp2, "id": did2, "flow": "authorize_continue"}, separators=(",", ":"))
                    sr2_resp = login_client.post(
                        OPENAI_API_ENDPOINTS["sentinel"],
                        headers={"origin": "https://sentinel.openai.com", "referer": SENTINEL_FRAME_URL, "content-type": "text/plain;charset=UTF-8"},
                        data=sr2,
                    )
                    if sr2_resp.status_code == 200:
                        d2 = sr2_resp.json()
                        pm2 = d2.get("proofofwork") or {}
                        if pm2.get("required") and pm2.get("seed"):
                            sp2 = gen2.generate_token(str(pm2.get("seed") or ""), str(pm2.get("difficulty") or "0"))
                        tr2 = (d2.get("turnstile") or {}).get("dx", "")
                        tv2 = ""
                        if tr2:
                            try: tv2 = gen2.decrypt_turnstile(tr2, sp2)
                            except: pass
                        sen2 = SentinelPayload(p=sp2, t=tv2, c=str(d2.get("token") or ""), flow="authorize_continue")
                        self._log("Codex sentinel obtained successfully")
                except Exception as e:
                    self._log(f"Codex sentinel failed: {e}", "warning")

                # authorize/continue submit email (no screen_hint, let codex_cli_simplified_flow decide)
                signup_headers = {
                    "referer": f"{OPENAI_AUTH}/log-in",
                    "accept": "application/json",
                    "content-type": "application/json",
                }
                if sen2 and did2:
                    signup_headers["openai-sentinel-token"] = json.dumps({
                        "p": sen2.p, "t": sen2.t, "c": sen2.c,
                        "id": did2, "flow": sen2.flow,
                    }, separators=(",", ":"))

                signup_body = json.dumps({"username": {"value": self.email, "kind": "email"}, "screen_hint": "signup"})
                signup_resp = login_session.post(
                    OPENAI_API_ENDPOINTS["signup"], headers=signup_headers, data=signup_body
                )
                self._log(f"Codex authorize/continue: {signup_resp.status_code}")
                if signup_resp.status_code != 200:
                    raise RuntimeError(f"authorize/continue failed: {signup_resp.text[:200]}")

                page_type = signup_resp.json().get("page", {}).get("type", "")
                self._log(f"Codex page_type: {page_type}")

                # If email_otp_send or email_otp_verification is returned, go through OTP flow
                if page_type in ("email_otp_send", "email_otp_verification"):
                    # Send OTP
                    if page_type == "email_otp_send":
                        login_session.get(OPENAI_API_ENDPOINTS["send_otp"], headers={
                            "referer": f"{OPENAI_AUTH}/email-verification",
                        }, timeout=15)
                        self._log("Codex OTP sent")

                    # Wait for OTP
                    self._otp_sent_at = time.time()
                    code = self._get_verification_code()
                    if not code:
                        raise RuntimeError("Failed to get Codex OTP")
                    self._log(f"Codex OTP: {code}")

                    # Verify OTP
                    otp_resp = login_session.post(
                        OPENAI_API_ENDPOINTS["validate_otp"],
                        headers={
                            "referer": f"{OPENAI_AUTH}/email-verification",
                            "accept": "application/json",
                            "content-type": "application/json",
                        },
                        data=json.dumps({"code": code}),
                    )
                    self._log(f"Codex OTP validate: {otp_resp.status_code}")
                    if otp_resp.status_code != 200:
                        raise RuntimeError(f"Codex OTP verification failed: {otp_resp.text[:200]}")

                    otp_data = otp_resp.json()
                    otp_page = otp_data.get("page", {}).get("type", "")
                    self._log(f"Codex OTP -> page_type={otp_page}")

                    if otp_page == "add_phone":
                        self._log("Codex CLI still requires add_phone, skipping", "warning")
                        raise RuntimeError("add_phone required")

                    # After OTP success, re-visit OAuth URL to get callback
                    self._log("Codex: re-visiting OAuth URL...")
                    resp = login_session.get(codex_oauth.auth_url, allow_redirects=False, timeout=15)
                    codex_callback = None
                    current_url = codex_oauth.auth_url
                    for i in range(15):
                        if resp.status_code not in (301, 302, 303, 307, 308):
                            break
                        location = resp.headers.get("Location", "")
                        if not location:
                            break
                        next_url = urllib.parse.urljoin(current_url, location)
                        self._log(f"Codex redirect {i+1}: {next_url[:80]}...")
                        if "code=" in next_url and "state=" in next_url:
                            codex_callback = next_url
                            break
                        current_url = next_url
                        resp = login_session.get(current_url, allow_redirects=False, timeout=15)

                    if codex_callback:
                        self._log("Codex CLI callback obtained successfully")
                        token_json = submit_callback_url(
                            callback_url=codex_callback,
                            expected_state=codex_oauth.state,
                            code_verifier=codex_oauth.code_verifier,
                            redirect_uri=CODEX_REDIRECT_URI,
                            client_id=CODEX_CLIENT_ID,
                            proxy_url=self.proxy_url,
                        )
                        codex_token_info = json.loads(token_json)
                        self._log(f"Codex token success: keys={list(codex_token_info.keys())}")
                    else:
                        self._log(f"Codex callback not obtained (status={resp.status_code})", "warning")
                else:
                    self._log(f"Codex non-OTP flow ({page_type}), skipping", "warning")
            except Exception as e:
                self._log(f"Codex CLI login failed: {e}", "warning")

            # Extract account info (prefer Codex token, fallback to NextAuth session)
            if codex_token_info and codex_token_info.get("access_token"):
                self._log("Using Codex CLI token (full refresh_token + id_token)")
                result.account_id = codex_token_info.get("account_id", "") or account_cookie or ""
                result.access_token = codex_token_info.get("access_token", "")
                result.refresh_token = codex_token_info.get("refresh_token", "")
                result.id_token = codex_token_info.get("id_token", "")
            else:
                self._log("Using NextAuth session token", "warning")
                result.account_id = account_cookie or ""
                result.access_token = access_token
                result.refresh_token = ""
                # access_token JWT contains chatgpt_account_id equivalent to id_token claims
                result.id_token = access_token

            result.password = self.password or ""
            result.source = "login" if self._is_existing_account else "register"

            if session_token:
                self.session_token = session_token
                result.session_token = session_token
                self._log("Got Session Token")

            # 17. Done
            self._log("=" * 60)
            if self._is_existing_account:
                self._log("Login successful! (existing account)")
            else:
                self._log("Registration successful!")
            self._log(f"Email: {result.email}")
            self._log(f"Account ID: {result.account_id}")
            self._log(f"Workspace ID: {result.workspace_id}")
            self._log("=" * 60)

            result.success = True
            result.metadata = {
                "email_service": self.email_service.service_type.value,
                "proxy_used": self.proxy_url,
                "registered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "is_existing_account": self._is_existing_account,
            }

            return result

        except Exception as e:
            self._log(f"Unexpected error during registration: {e}", "error")
            result.error_message = str(e)
            return result

    def save_to_database(self, result: RegistrationResult) -> bool:
        """
        Save registration result to database

        Args:
            result: Registration result

        Returns:
            Whether save was successful
        """
        if not result.success:
            return False

        return True  # Storage handled by account_manager
