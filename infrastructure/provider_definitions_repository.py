from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from core.db import ProviderDefinitionModel, ProviderSettingModel, engine

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_BUILTIN_DEFINITIONS: list[dict] = [
    # ── mailbox ──────────────────────────────────────────────────────
    {
        "provider_type": "mailbox",
        "provider_key": "cfworker_admin_api",
        "label": "CF Worker (self-hosted domain)",
        "description": "Custom domain mailbox based on Cloudflare Worker, requires self-deployed Worker backend",
        "driver_type": "cfworker_admin_api",
        "default_auth_mode": "token",
        "enabled": True,
        "category": "selfhost",
        "auth_modes": [{"value": "token", "label": "Token auth"}],
        "fields": [
            {"key": "cfworker_api_url", "label": "API URL", "placeholder": "https://your-worker.example.com", "category": "connection"},
            {"key": "cfworker_admin_token", "label": "Admin Token", "secret": True, "category": "auth"},
            {"key": "cfworker_domain", "label": "Email domain", "placeholder": "example.com", "category": "connection"},
            {"key": "cfworker_fingerprint", "label": "Fingerprint ID (optional)", "placeholder": "", "category": "connection"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "moemail_api",
        "label": "MoeMail（sall.cc）",
        "description": "Self-deployed temporary mailbox, supports auto-registering accounts or manually logging in to existing accounts",
        "driver_type": "moemail_api",
        "default_auth_mode": "password",
        "enabled": True,
        "category": "selfhost",
        "auth_modes": [
            {"value": "password", "label": "Username & password"},
            {"value": "token", "label": "Session Token"},
        ],
        "fields": [
            {"key": "moemail_api_url", "label": "API URL", "placeholder": "https://moemail.example.com", "category": "connection"},
            {"key": "moemail_username", "label": "Username (optional)", "category": "auth"},
            {"key": "moemail_password", "label": "Password (optional)", "secret": True, "category": "auth"},
            {"key": "moemail_session_token", "label": "Session Token (optional)", "secret": True, "category": "auth"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "tempmail_lol_api",
        "label": "TempMail.lol",
        "description": "Free temporary mailbox, ready to use without any configuration",
        "driver_type": "tempmail_lol_api",
        "default_auth_mode": "",
        "enabled": True,
        "category": "free",
        "auth_modes": [],
        "fields": [],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "tempmail_web_api",
        "label": "Temp-Mail.org",
        "description": "Free temporary mailbox, requires browser environment (Camoufox)",
        "driver_type": "tempmail_web_api",
        "default_auth_mode": "",
        "enabled": True,
        "category": "free",
        "auth_modes": [],
        "fields": [
            {"key": "tempmail_web_base_url", "label": "API URL (optional)", "placeholder": "https://web2.temp-mail.org", "category": "connection"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "duckmail_api",
        "label": "DuckMail (auto-generate)",
        "description": "Self-deployed mailbox service, auto-generates temporary mailboxes via API",
        "driver_type": "duckmail_api",
        "default_auth_mode": "bearer",
        "enabled": True,
        "category": "selfhost",
        "auth_modes": [{"value": "bearer", "label": "Bearer Token"}],
        "fields": [
            {"key": "duckmail_api_url", "label": "API URL", "placeholder": "https://duckmail.example.com", "category": "connection"},
            {"key": "duckmail_provider_url", "label": "Provider URL (optional)", "placeholder": "", "category": "connection"},
            {"key": "duckmail_bearer", "label": "Bearer Token", "secret": True, "category": "auth"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "freemail_api",
        "label": "FreeMail (auto-generate)",
        "description": "Self-deployed mailbox service, supports username/password or Admin Token auth",
        "driver_type": "freemail_api",
        "default_auth_mode": "password",
        "enabled": True,
        "category": "selfhost",
        "auth_modes": [{"value": "password", "label": "Username & password"}, {"value": "token", "label": "Admin Token"}],
        "fields": [
            {"key": "freemail_api_url", "label": "API URL", "placeholder": "https://freemail.example.com", "category": "connection"},
            {"key": "freemail_admin_token", "label": "Admin Token", "secret": True, "category": "auth"},
            {"key": "freemail_username", "label": "Username", "category": "auth"},
            {"key": "freemail_password", "label": "Password", "secret": True, "category": "auth"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "testmail_api",
        "label": "Testmail (namespace mailbox)",
        "description": "Testmail.app third-party service, auto-generates email addresses via API Key and Namespace",
        "driver_type": "testmail_api",
        "default_auth_mode": "apikey",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "apikey", "label": "API Key"}],
        "fields": [
            {"key": "testmail_api_url", "label": "API URL (optional)", "placeholder": "https://api.testmail.app", "category": "connection"},
            {"key": "testmail_api_key", "label": "API Key", "secret": True, "category": "auth"},
            {"key": "testmail_namespace", "label": "Namespace", "category": "identity"},
            {"key": "testmail_tag_prefix", "label": "Tag prefix (optional)", "placeholder": "", "category": "identity"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "laoudo_api",
        "label": "Laoudo (fixed mailbox)",
        "description": "laoudo.com fixed domain mailbox, uses existing email address to receive verification codes",
        "driver_type": "laoudo_api",
        "default_auth_mode": "token",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "token", "label": "JWT Token"}],
        "fields": [
            {"key": "laoudo_auth", "label": "Auth Token", "secret": True, "category": "auth"},
            {"key": "laoudo_email", "label": "Email address", "placeholder": "your@email.com", "category": "identity"},
            {"key": "laoudo_account_id", "label": "Account ID", "category": "identity"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "aitre_api",
        "label": "Aitre temporary mailbox",
        "description": "mail.aitre.cc free temporary mailbox, requires specifying a fixed email address",
        "driver_type": "aitre_api",
        "default_auth_mode": "",
        "enabled": True,
        "category": "free",
        "auth_modes": [],
        "fields": [
            {"key": "aitre_email", "label": "Email address", "placeholder": "your@email.com", "category": "identity"},
            {"key": "aitre_api_url", "label": "API URL (optional)", "placeholder": "https://mail.aitre.cc/api/tempmail", "category": "connection"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "ddg_email",
        "label": "DuckDuckGo Email",
        "description": "DuckDuckGo Email Protection, generates @duck.com aliases, reads verification codes via IMAP from forwarding mailbox",
        "driver_type": "ddg_email",
        "default_auth_mode": "bearer",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "bearer", "label": "Bearer Token"}],
        "fields": [
            {"key": "ddg_bearer", "label": "DDG Bearer Token", "secret": True, "category": "auth"},
            {"key": "ddg_imap_host", "label": "IMAP server (optional)", "placeholder": "auto-inferred", "category": "connection"},
            {"key": "ddg_imap_user", "label": "IMAP username (forwarding mailbox)", "placeholder": "your@gmail.com", "category": "auth"},
            {"key": "ddg_imap_pass", "label": "IMAP password", "secret": True, "category": "auth"},
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "generic_http_mailbox",
        "label": "Generic HTTP mailbox",
        "description": "Connect to any mailbox API via configurable HTTP endpoints and auth methods, suitable for advanced users",
        "driver_type": "generic_http_mailbox",
        "default_auth_mode": "",
        "enabled": True,
        "category": "custom",
        "auth_modes": [],
        "fields": [],
    },
    # ── captcha ──────────────────────────────────────────────────────
    {
        "provider_type": "captcha",
        "provider_key": "yescaptcha_api",
        "label": "YesCaptcha",
        "description": "YesCaptcha cloud captcha recognition service, supports Turnstile and other types",
        "driver_type": "yescaptcha_api",
        "default_auth_mode": "apikey",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "apikey", "label": "API Key"}],
        "fields": [
            {"key": "yescaptcha_key", "label": "Client Key", "secret": True},
        ],
    },
    {
        "provider_type": "captcha",
        "provider_key": "twocaptcha_api",
        "label": "2Captcha",
        "description": "2Captcha cloud captcha recognition service, supports Turnstile and other types",
        "driver_type": "twocaptcha_api",
        "default_auth_mode": "apikey",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "apikey", "label": "API Key"}],
        "fields": [
            {"key": "twocaptcha_key", "label": "API Key", "secret": True},
        ],
    },
    {
        "provider_type": "captcha",
        "provider_key": "local_solver",
        "label": "Local captcha solver",
        "description": "Calls local api_solver service (Camoufox/patchright) to solve Turnstile captchas",
        "driver_type": "local_solver",
        "default_auth_mode": "",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [
            {"key": "solver_url", "label": "Solver URL", "placeholder": "http://localhost:8889"},
        ],
    },
    {
        "provider_type": "captcha",
        "provider_key": "manual",
        "label": "Manual captcha",
        "description": "Blocks and waits for user to manually input captcha, suitable for debugging",
        "driver_type": "manual",
        "default_auth_mode": "",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [],
    },
    # ── sms ──────────────────────────────────────────────────────────
    {
        "provider_type": "sms",
        "provider_key": "herosms_api",
        "label": "HeroSMS",
        "description": "HeroSMS SMS platform, supports number reuse and auto-resend",
        "driver_type": "herosms_api",
        "default_auth_mode": "apikey",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "apikey", "label": "API Key"}],
        "fields": [
            {"key": "herosms_api_key", "label": "API Key", "secret": True},
            {"key": "herosms_default_country", "label": "Default country code", "placeholder": "187 (USA)"},
            {"key": "herosms_default_service", "label": "Default service code", "placeholder": "dr"},
            {"key": "herosms_max_price", "label": "Max price (optional)", "placeholder": "-1"},
            {"key": "register_phone_extra_max", "label": "Number reuse extra limit", "placeholder": "3"},
            {"key": "register_reuse_phone_to_max", "label": "Reuse number to max", "placeholder": "true"},
        ],
    },
    {
        "provider_type": "sms",
        "provider_key": "sms_activate_api",
        "label": "SMS-Activate",
        "description": "SMS-Activate SMS platform (sms-activate.guru)",
        "driver_type": "sms_activate_api",
        "default_auth_mode": "apikey",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "apikey", "label": "API Key"}],
        "fields": [
            {"key": "sms_activate_api_key", "label": "API Key", "secret": True},
            {"key": "sms_activate_default_country", "label": "Default country code", "placeholder": "ru"},
        ],
    },
    # ── proxy ────────────────────────────────────────────────────────
    {
        "provider_type": "proxy",
        "provider_key": "api_extract",
        "label": "API extract proxy",
        "description": "Dynamically extract proxy IP lists via HTTP API, compatible with most proxy providers' API extraction interfaces",
        "driver_type": "api_extract",
        "default_auth_mode": "",
        "enabled": False,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [
            {"key": "proxy_api_url", "label": "API URL", "placeholder": "https://provider.com/api/get_proxy?key=xxx"},
            {"key": "proxy_protocol", "label": "Protocol", "placeholder": "http / socks5"},
            {"key": "proxy_username", "label": "Username (optional)"},
            {"key": "proxy_password", "label": "Password (optional)", "secret": True},
        ],
    },
    {
        "provider_type": "proxy",
        "provider_key": "rotating_gateway",
        "label": "Rotating gateway proxy",
        "description": "Fixed gateway address, auto-assigns different exit IPs per request, suitable for BrightData / Oxylabs / IPRoyal etc.",
        "driver_type": "rotating_gateway",
        "default_auth_mode": "",
        "enabled": False,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [
            {"key": "proxy_gateway_url", "label": "Gateway URL", "placeholder": "http://user:pass@gate.example.com:7777"},
        ],
    },
]


class ProviderDefinitionsRepository:

    def ensure_seeded(self) -> None:
        """Seed built-in provider definition data into the database.

        New entries are inserted, existing entries have their field definitions
        updated (label, description, fields, etc.), ensuring that built-in
        provider metadata stays in sync after code upgrades.
        """
        with Session(engine) as session:
            existing: dict[str, ProviderDefinitionModel] = {}
            for row in session.exec(select(ProviderDefinitionModel)).all():
                key = f"{row.provider_type}::{row.provider_key}"
                existing[key] = row

            changed = False
            for seed in _BUILTIN_DEFINITIONS:
                key = f"{seed['provider_type']}::{seed['provider_key']}"
                item = existing.get(key)

                if item is None:
                    # New entry
                    item = ProviderDefinitionModel(
                        provider_type=seed["provider_type"],
                        provider_key=seed["provider_key"],
                        created_at=_utcnow(),
                    )
                    logger.info("Seed data: added %s/%s", seed["provider_type"], seed["provider_key"])

                # Update metadata (sync on every startup to ensure code changes take effect)
                item.label = seed.get("label", seed["provider_key"])
                item.description = seed.get("description", "")
                item.driver_type = seed.get("driver_type", seed["provider_key"])
                item.default_auth_mode = seed.get("default_auth_mode", "")
                item.enabled = seed.get("enabled", True)
                item.is_builtin = True
                item.category = seed.get("category", "")
                item.set_auth_modes(list(seed.get("auth_modes") or []))
                item.set_fields(list(seed.get("fields") or []))
                if not item.get_metadata():
                    # Only write seed value when metadata is empty, to avoid overwriting user-customized pipelines
                    item.set_metadata(dict(seed.get("metadata") or {}))
                item.updated_at = _utcnow()
                session.add(item)
                changed = True

            if changed:
                session.commit()

    # ── Query (all from DB) ────────────────────────────────────────────

    def list_by_type(self, provider_type: str, *, enabled_only: bool = False) -> list[ProviderDefinitionModel]:
        with Session(engine) as session:
            query = select(ProviderDefinitionModel).where(ProviderDefinitionModel.provider_type == provider_type)
            if enabled_only:
                query = query.where(ProviderDefinitionModel.enabled == True)  # noqa: E712
            return session.exec(query.order_by(ProviderDefinitionModel.id)).all()

    def get_by_key(self, provider_type: str, provider_key: str) -> ProviderDefinitionModel | None:
        with Session(engine) as session:
            return session.exec(
                select(ProviderDefinitionModel)
                .where(ProviderDefinitionModel.provider_type == provider_type)
                .where(ProviderDefinitionModel.provider_key == provider_key)
            ).first()

    def list_driver_templates(self, provider_type: str) -> list[dict]:
        """Read from DB: deduplicate by driver_type, return available driver template list."""
        with Session(engine) as session:
            definitions = session.exec(
                select(ProviderDefinitionModel)
                .where(ProviderDefinitionModel.provider_type == provider_type)
                .order_by(ProviderDefinitionModel.is_builtin.desc(), ProviderDefinitionModel.id)
            ).all()
        seen: dict[str, dict] = {}
        for d in definitions:
            dt = d.driver_type or ""
            if dt and dt not in seen:
                seen[dt] = {
                    "provider_type": d.provider_type,
                    "provider_key": d.provider_key,
                    "driver_type": dt,
                    "label": d.label,
                    "description": d.description,
                    "default_auth_mode": d.default_auth_mode,
                    "auth_modes": d.get_auth_modes(),
                    "fields": d.get_fields(),
                }
        return list(seen.values())

    def _get_driver_defaults(self, provider_type: str, driver_type: str) -> dict | None:
        """Find existing definition with same driver_type from DB as template."""
        with Session(engine) as session:
            ref = session.exec(
                select(ProviderDefinitionModel)
                .where(ProviderDefinitionModel.provider_type == provider_type)
                .where(ProviderDefinitionModel.driver_type == driver_type)
                .order_by(ProviderDefinitionModel.is_builtin.desc(), ProviderDefinitionModel.id)
            ).first()
            if not ref:
                return None
            return {
                "default_auth_mode": ref.default_auth_mode,
                "auth_modes": ref.get_auth_modes(),
                "fields": ref.get_fields(),
            }

    # ── Write ────────────────────────────────────────────────────────

    def save(
        self,
        *,
        definition_id: int | None,
        provider_type: str,
        provider_key: str,
        label: str,
        description: str,
        driver_type: str,
        enabled: bool,
        default_auth_mode: str = "",
        metadata: dict | None = None,
    ) -> ProviderDefinitionModel:
        defaults = self._get_driver_defaults(provider_type, driver_type)

        with Session(engine) as session:
            if definition_id:
                item = session.get(ProviderDefinitionModel, definition_id)
                if not item:
                    raise ValueError("Provider definition does not exist")
            else:
                item = session.exec(
                    select(ProviderDefinitionModel)
                    .where(ProviderDefinitionModel.provider_type == provider_type)
                    .where(ProviderDefinitionModel.provider_key == provider_key)
                ).first()
                if not item:
                    item = ProviderDefinitionModel(
                        provider_type=provider_type,
                        provider_key=provider_key,
                    )
                    item.created_at = _utcnow()

            item.provider_type = provider_type
            item.provider_key = provider_key
            item.label = label or provider_key
            item.description = description or ""
            item.driver_type = driver_type
            item.default_auth_mode = default_auth_mode or item.default_auth_mode or (defaults.get("default_auth_mode", "") if defaults else "")
            item.enabled = bool(enabled)
            if not item.get_auth_modes() and defaults:
                item.set_auth_modes(list(defaults.get("auth_modes") or []))
            if not item.get_fields() and defaults:
                item.set_fields(list(defaults.get("fields") or []))
            item.set_metadata(dict(metadata or {}))
            item.updated_at = _utcnow()
            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def delete(self, definition_id: int) -> bool:
        with Session(engine) as session:
            item = session.get(ProviderDefinitionModel, definition_id)
            if not item:
                return False
            has_settings = session.exec(
                select(ProviderSettingModel)
                .where(ProviderSettingModel.provider_type == item.provider_type)
                .where(ProviderSettingModel.provider_key == item.provider_key)
            ).first()
            if has_settings:
                raise ValueError("Please delete the corresponding provider settings before deleting the definition")
            session.delete(item)
            session.commit()
            return True