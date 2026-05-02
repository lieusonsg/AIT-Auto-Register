"""Manual captcha solver — blocks waiting for human input."""
from core.base_captcha import BaseCaptcha
from providers.registry import register_provider


@register_provider("captcha", "manual")
class ManualCaptcha(BaseCaptcha):
    """Manual captcha solving, blocks waiting for user input"""

    @classmethod
    def from_config(cls, config: dict) -> 'ManualCaptcha':
        return cls()

    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        return input(f"Please manually obtain Turnstile token ({page_url}): ").strip()

    def solve_image(self, image_b64: str) -> str:
        return input("Please enter image captcha: ").strip()
