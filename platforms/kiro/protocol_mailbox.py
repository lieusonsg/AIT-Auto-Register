"""Kiro protocol mailbox registration worker."""
from __future__ import annotations

from typing import Callable

from platforms.kiro.core import KiroRegister, _pwd, wait_for_otp


class KiroProtocolMailboxWorker:
    def __init__(self, *, proxy: str | None = None, tag: str = "KIRO", log_fn: Callable[[str], None] = print):
        self.client = KiroRegister(proxy=proxy, tag=tag)
        self.client.log = lambda msg: log_fn(msg)

    def run(
        self,
        *,
        email: str,
        password: str | None = None,
        name: str = "Kiro User",
        mail_token: str | None = None,
        otp_timeout: int = 120,
        otp_callback=None,
    ) -> dict:
        use_password = password or _pwd()
        self.client.log(f"  Auto-generated password: {use_password}" if not password else f"  Using provided password: {use_password}")
        self.client.log(f"========== Starting registration: {email} ==========")

        redir = self.client.step1_kiro_init()
        if not redir:
            raise RuntimeError("InitiateLogin failed")
        if not self.client.step2_get_wsh(redir):
            raise RuntimeError("Failed to get wsh")
        if not self.client.step3_signin_flow(email):
            raise RuntimeError("Signin flow failed")
        if not self.client.step4_signup_flow(email):
            raise RuntimeError("Signup flow failed")
        if not self.client.profile_wf_id:
            raise RuntimeError("Failed to get workflowID")
        tes = self.client.step5_get_tes_token()
        if not tes:
            self.client.log("  Warning: TES token fetch failed, continuing...")
        if not self.client.step6_profile_load():
            raise RuntimeError("Profile start failed")
        if self.client.step7_send_otp(email) is None:
            raise RuntimeError("Send OTP failed")

        if otp_callback:
            self.client.log("  Auto-fetching verification code...")
            otp = otp_callback()
        elif mail_token:
            self.client.log("  Auto-fetching verification code...")
            otp = wait_for_otp(mail_token, timeout=otp_timeout, tag=self.client.tag)
        else:
            otp = input(f"[{self.client.tag}] Enter verification code: ").strip()
        if not otp:
            raise RuntimeError("Failed to get verification code")

        identity = self.client.step8_create_identity(otp, email, name)
        if not identity:
            raise RuntimeError("create-identity failed")
        reg_code = identity["registrationCode"]
        sign_in_state = identity["signInState"]

        signup_registration = self.client.step9_signup_registration(reg_code, sign_in_state)
        if not signup_registration:
            raise RuntimeError("Signup registration failed")
        password_state = self.client.step10_set_password(use_password, email, signup_registration)
        if not password_state:
            raise RuntimeError("Failed to set password")

        login_result = self.client.step11_final_login(email, password_state)
        if not login_result:
            self.client.log("  Warning: Final login step failed, but account may have been created")

        tokens = self.client.step12_get_tokens()
        if not tokens:
            self.client.log("Registration complete! (but token fetch failed, account is usable)")
            return {"email": email, "password": use_password, "name": name}

        bearer_token = tokens["sessionToken"]
        device_tokens = self.client.step12f_device_auth(bearer_token)
        if device_tokens:
            self.client.log("Registration complete! (with accessToken + sessionToken + refreshToken)")
            return {
                "email": email,
                "password": use_password,
                "name": name,
                "accessToken": tokens["accessToken"],
                "sessionToken": tokens["sessionToken"],
                "clientId": device_tokens["clientId"],
                "clientSecret": device_tokens["clientSecret"],
                "refreshToken": device_tokens["refreshToken"],
            }

        self.client.log("Registration complete! (with accessToken + sessionToken, but refreshToken fetch failed)")
        return {
            "email": email,
            "password": use_password,
            "name": name,
            "accessToken": tokens["accessToken"],
            "sessionToken": tokens["sessionToken"],
        }
