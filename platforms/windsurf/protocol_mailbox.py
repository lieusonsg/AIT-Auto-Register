"""Windsurf protocol mailbox registration worker."""
from __future__ import annotations

import re
from typing import Callable, Optional

from platforms.windsurf.core import WindsurfClient


class WindsurfProtocolMailboxWorker:
    def __init__(self, *, proxy: str | None = None, log_fn: Callable[[str], None] = print):
        self.client = WindsurfClient(proxy=proxy, log_fn=log_fn)
        self.log = log_fn

    def run(
        self,
        *,
        email: str,
        password: str,
        name: str,
        otp_callback: Optional[Callable[[], str]] = None,
    ) -> dict:
        if not otp_callback:
            raise RuntimeError("otp_callback is required")

        try:
            self.client.fetch_connections(email)
            self.client.check_user_login_method(email)
        except Exception as exc:
            self.log(f"Windsurf registration pre-check failed, continuing with email verification flow: {exc}")

        verification_token = self.client.start_email_signup(email)
        raw_code = otp_callback()
        code = self._extract_code(raw_code)
        self.log(f"Obtained Windsurf verification code: {code}")

        complete = self.client.complete_email_signup(
            email=email,
            verification_token=verification_token,
            code=code,
            password=password,
            name=name,
        )
        auth_token = str(complete.get("token") or "")
        auth = self.client.post_auth(auth_token)
        session_token = auth["session_token"]
        account_id = auth.get("account_id", "")
        org_id = auth.get("org_id", "")
        state = self.client.load_account_state(
            session_token=session_token,
            account_id=account_id,
            org_id=org_id,
            fallback_email=email,
        )
        summary = dict(state.get("summary") or {})
        overview = dict(summary.get("account_overview") or {})
        self.log(
            f"Windsurf registration successful: {email} "
            f"plan={overview.get('plan_name', 'unknown')} "
            f"quota={overview.get('remaining_credits', '-')}"
        )
        return {
            "email": str(complete.get("email") or email),
            "password": password,
            "name": name,
            "user_id": str(complete.get("user_id") or (overview.get("remote_user") or {}).get("user_id") or ""),
            "auth_token": auth_token,
            "session_token": session_token,
            "account_id": account_id,
            "org_id": org_id,
            "account_overview": overview,
            "state_summary": summary,
        }

    @staticmethod
    def _extract_code(raw: str) -> str:
        text = str(raw or "")
        match = re.search(r"\b(\d{6})\b", text)
        if match:
            return match.group(1)
        raise RuntimeError(f"Cannot extract Windsurf 6-digit verification code from email content: {text[:200]}")

