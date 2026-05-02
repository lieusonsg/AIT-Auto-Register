"""blink.new protocol mailbox registration worker."""
from __future__ import annotations

import re
from typing import Callable, Optional

from platforms.blink.core import BLINK_BASE, BLINK_PRICE_IDS, BlinkRegister, summarize_blink_account_state


class BlinkProtocolMailboxWorker:
    def __init__(self, *, proxy: str | None = None, log_fn: Callable[[str], None] = print):
        self.client = BlinkRegister(proxy=proxy)
        self.client._log = log_fn
        self.log = log_fn

    def run(
        self,
        *,
        email: str,
        link_callback: Optional[Callable[[], str]] = None,
    ) -> dict:
        """Complete registration flow, returns Blink account fields needed for persistence."""
        # Step 1: Trigger magic link email
        ok = self.client.step1_send_magic_link(email)
        if not ok:
            raise RuntimeError("Failed to send magic link")

        # Step 2: Wait for email and extract token
        if not link_callback:
            raise RuntimeError("link_callback is required")
        self.log("Waiting for magic link...")
        raw = link_callback()
        if not raw:
            raise RuntimeError("Timed out getting magic link")

        # otp_callback may return a full URL or a plain token
        token = self._extract_token(raw)
        self.log(f"magic_token={token[:16]}...")

        # Step 3: Redeem customToken
        auth_data = self.client.step2_redeem_magic_link(token, email)
        custom_token = auth_data["customToken"]
        user = auth_data["user"]
        workspace_slug = auth_data.get("workspaceSlug", "")

        # Step 4: Firebase login to get idToken
        firebase_data = self.client.step3_firebase_signin(custom_token)
        id_token = firebase_data["idToken"]
        firebase_refresh_token = firebase_data["refreshToken"]

        # Step 5: Get Blink app token
        app_token_data = self.client.step4_exchange_app_token(id_token, workspace_slug=workspace_slug)
        access_token = app_token_data.get("access_token", "")
        refresh_token = app_token_data.get("refresh_token", "")

        # Step 6: Get session cookie (for browser login)
        session_token = self.client.step5_get_session_token(id_token, workspace_slug=workspace_slug)

        # Step 7: Create user record
        user_info = self.client.step6_create_user(
            id_token,
            email,
            user_id=user.get("id", ""),
            workspace_slug=workspace_slug,
        )
        workspace_id = user_info.get("active_workspace_id", "")

        # Step 8: Post-registration (credit migration + referral code)
        post_register = self.client.step7_post_register(
            id_token,
            user_id=user.get("id", ""),
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
        )

        # Step 9: Fetch session-data once, save normalized plan/credit summary
        session_data = self.client.fetch_session_data(
            id_token,
            session_token=session_token,
            workspace_slug=workspace_slug,
        )
        summary = summarize_blink_account_state(session_data, fallback_email=email)
        overview = summary["account_overview"]
        resolved_workspace_id = str(workspace_id or summary.get("workspace_id") or "").strip()
        cashier_url, checkout_session_id = self._maybe_create_checkout_link(
            id_token=id_token,
            session_token=session_token,
            workspace_id=resolved_workspace_id,
            workspace_slug=workspace_slug,
        )
        if cashier_url:
            overview["cashier_url"] = cashier_url
        if checkout_session_id:
            overview["checkout_session_id"] = checkout_session_id

        result = {
            "success": True,
            "email": email,
            "password": "",
            "user_id": user.get("id", ""),
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "firebase_refresh_token": firebase_refresh_token,
            "session_token": session_token,
            "workspace_slug": workspace_slug,
            "workspace_id": resolved_workspace_id,
            "customer_id": summary.get("customer_id", ""),
            "referral_code": post_register.get("referral_code", "") or summary.get("referral_code", ""),
            "cashier_url": cashier_url,
            "checkout_session_id": checkout_session_id,
            "account_overview": overview,
        }
        self.log(
            f"Registration successful: {email} workspace={workspace_slug} "
            f"plan={overview.get('plan_name', 'unknown')} "
            f"billing_limit={overview.get('billing_period_credits_limit', 0)}"
        )
        if cashier_url:
            self.log(f"Auto-generated payment link: {cashier_url}")
        return result

    def _maybe_create_checkout_link(
        self,
        *,
        id_token: str,
        session_token: str,
        workspace_id: str,
        workspace_slug: str,
    ) -> tuple[str, str]:
        price_id = str(BLINK_PRICE_IDS.get("pro") or "").strip()
        if not workspace_id:
            self.log("Skipping auto payment link generation: missing workspace_id")
            return "", ""
        if not price_id:
            self.log("Skipping auto payment link generation: Blink Pro price_id not configured")
            return "", ""

        cancel_url = (
            f"{BLINK_BASE}/{workspace_slug}?showPricing=true"
            if workspace_slug
            else f"{BLINK_BASE}/?showPricing=true"
        )
        try:
            checkout = self.client.create_checkout(
                id_token,
                price_id=price_id,
                plan_id="pro",
                workspace_id=workspace_id,
                cancel_url=cancel_url,
                session_token=session_token,
                workspace_slug=workspace_slug,
            )
        except Exception as exc:
            self.log(f"Auto payment link generation failed, skipping: {exc}")
            return "", ""

        cashier_url = str(checkout.get("url") or "").strip()
        checkout_session_id = str(checkout.get("sessionId") or "").strip()
        return cashier_url, checkout_session_id

    @staticmethod
    def _extract_token(raw: str) -> str:
        """Extract magic_token from a full URL or raw string."""
        m = re.search(r'magic_token=([a-f0-9]{64})', raw)
        if m:
            return m.group(1)
        # If it's a raw 64-character hex token
        raw = raw.strip()
        if re.fullmatch(r'[a-f0-9]{64}', raw):
            return raw
        raise RuntimeError(f"Unable to extract magic_token from email content: {raw[:200]}")
