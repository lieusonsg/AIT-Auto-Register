"""OpenAI dedicated HTTP client"""
from typing import Any, Dict, Optional, Tuple

from core.http_client import HTTPClient, HTTPClientError, RequestConfig
from .constants import ERROR_MESSAGES
import logging
logger = logging.getLogger(__name__)

class OpenAIHTTPClient(HTTPClient):
    """
    OpenAI dedicated HTTP client
    Contains OpenAI API specific request methods
    """

    def __init__(
        self,
        proxy_url: Optional[str] = None,
        config: Optional[RequestConfig] = None
    ):
        """
        Initialize OpenAI HTTP client

        Args:
            proxy_url: Proxy URL
            config: Request configuration
        """
        super().__init__(proxy_url, config)

        # OpenAI-specific default configuration
        if config is None:
            self.config.timeout = 30
            self.config.max_retries = 3

        # Default request headers
        self.default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }

    def check_ip_location(self) -> Tuple[bool, Optional[str]]:
        """
        Check IP geolocation

        Returns:
            Tuple[is_supported, location_info]
        """
        try:
            response = self.get("https://cloudflare.com/cdn-cgi/trace", timeout=10)
            trace_text = response.text

            # Parse location info
            import re
            loc_match = re.search(r"loc=([A-Z]+)", trace_text)
            loc = loc_match.group(1) if loc_match else None

            # Check if supported
            if loc in ["CN", "HK", "MO", "TW"]:
                return False, loc
            return True, loc

        except Exception as e:
            logger.error(f"Failed to check IP geolocation: {e}")
            return False, None

    def send_openai_request(
        self,
        endpoint: str,
        method: str = "POST",
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send OpenAI API request

        Args:
            endpoint: API endpoint
            method: HTTP method
            data: Form data
            json_data: JSON data
            headers: Request headers
            **kwargs: Other parameters

        Returns:
            Response JSON data

        Raises:
            HTTPClientError: Request failed
        """
        # Merge request headers
        request_headers = self.default_headers.copy()
        if headers:
            request_headers.update(headers)

        # Set Content-Type
        if json_data is not None and "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/json"
        elif data is not None and "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"

        try:
            response = self.request(
                method,
                endpoint,
                data=data,
                json=json_data,
                headers=request_headers,
                **kwargs
            )

            # Check response status code
            response.raise_for_status()

            # Try to parse JSON
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"raw_response": response.text}

        except cffi_requests.RequestsError as e:
            raise HTTPClientError(f"OpenAI request failed: {endpoint} - {e}")

    def check_sentinel(self, did: str, proxies: Optional[Dict] = None) -> Optional[str]:
        """
        Check Sentinel interception

        Args:
            did: Device ID
            proxies: Proxy configuration

        Returns:
            Sentinel token or None
        """
        from .constants import OPENAI_API_ENDPOINTS

        try:
            sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'

            response = self.post(
                OPENAI_API_ENDPOINTS["sentinel"],
                headers={
                    "origin": "https://sentinel.openai.com",
                    "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                    "content-type": "text/plain;charset=UTF-8",
                },
                data=sen_req_body,
            )

            if response.status_code == 200:
                return response.json().get("token")
            else:
                logger.warning(f"Sentinel check failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Sentinel check exception: {e}")
            return None


def create_http_client(
    proxy_url: Optional[str] = None,
    config: Optional[RequestConfig] = None
) -> HTTPClient:
    """
    HTTP client factory function

    Args:
        proxy_url: Proxy URL
        config: Request configuration

    Returns:
        HTTPClient instance
    """
    return HTTPClient(proxy_url, config)


def create_openai_client(
    proxy_url: Optional[str] = None,
    config: Optional[RequestConfig] = None
) -> OpenAIHTTPClient:
    """
    OpenAI HTTP client factory function

    Args:
        proxy_url: Proxy URL
        config: Request configuration

    Returns:
        OpenAIHTTPClient instance
    """
    return OpenAIHTTPClient(proxy_url, config)
