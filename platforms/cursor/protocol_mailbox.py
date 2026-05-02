"""Cursor protocol mailbox registration worker."""
from __future__ import annotations

from typing import Callable, Optional

from platforms.cursor.core import CursorRegister, _rand_password


class CursorProtocolMailboxWorker:
    def __init__(self, *, proxy: str | None = None, log_fn: Callable[[str], None] = print):
        self.client = CursorRegister(proxy=proxy, log_fn=log_fn)
        self.log = log_fn

    def run(
        self,
        *,
        email: str,
        password: str | None = None,
        otp_callback: Optional[Callable[[], str]] = None,
        captcha_solver=None,
    ) -> dict:
        use_password = password or _rand_password()
        self.log(f"Email: {email}")
        self.log("Step1: Getting session...")
        state_encoded, _ = self.client.step1_get_session()
        self.log("Step2: Submitting email...")
        self.client.step2_submit_email(email, state_encoded)
        self.log("Step3: Submitting password + Turnstile...")
        self.client.step3_submit_password(use_password, email, state_encoded, captcha_solver)
        self.log("Waiting for OTP email...")
        otp = otp_callback() if otp_callback else input("OTP: ")
        if not otp:
            raise RuntimeError("Failed to get verification code")
        self.log(f"Verification code: {otp}")
        self.log("Step4: Submitting OTP...")
        auth_code = self.client.step4_submit_otp(otp, email, state_encoded)
        self.log("Step5: Getting Token...")
        token = self.client.step5_get_token(auth_code, state_encoded)
        return {"email": email, "password": use_password, "token": token}
