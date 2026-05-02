from __future__ import annotations


class RegistrationError(RuntimeError):
    """Base exception for registration flow."""


class IdentityResolutionError(RegistrationError):
    """Identity resolution failed."""


class CaptchaConfigurationError(RegistrationError):
    """Captcha configuration unavailable."""


class OtpTimeoutError(RegistrationError):
    """Verification code wait timed out."""


class BrowserReuseRequiredError(RegistrationError):
    """Headless OAuth missing reusable browser session."""


class RegistrationUnsupportedError(RegistrationError):
    """Current platform or executor does not support this registration path."""

