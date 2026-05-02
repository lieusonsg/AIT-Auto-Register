"""
Constant definitions
"""

import os
import random
from datetime import datetime
from enum import Enum
from typing import Dict, List, Tuple


# ============================================================================
# Enum types
# ============================================================================

class AccountStatus(str, Enum):
    """Account status"""
    ACTIVE = "active"
    EXPIRED = "expired"
    BANNED = "banned"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """Task status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EmailServiceType(str, Enum):
    """Email service type"""
    TEMPMAIL = "tempmail"
    OUTLOOK = "outlook"
    CUSTOM_DOMAIN = "custom_domain"
    TEMP_MAIL = "temp_mail"


# ============================================================================
# Application constants
# ============================================================================

APP_NAME = "OpenAI/Codex CLI Auto Registration System"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "System for automatically registering OpenAI/Codex CLI accounts"

# ============================================================================
# OpenAI OAuth related constants
# ============================================================================

# OpenAI base URL (supports override via environment variables)
OPENAI_AUTH = os.environ.get("OPENAI_AUTH_BASE_URL", "https://auth.openai.com")
CHATGPT_APP = os.environ.get("CHATGPT_APP_URL", "https://chatgpt.com")
PLATFORM_LOGIN_ENTRY = os.environ.get("PLATFORM_LOGIN_ENTRY", "https://platform.openai.com/login")

# OAuth parameters (supports override via environment variables)
# Registration phase uses ChatGPT Web client (no add_phone requirement)
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "app_X8zY6vW2pQ9tR3dE7nK1jL5gH")
OAUTH_AUTH_URL = f"{OPENAI_AUTH}/api/accounts/authorize"
OAUTH_TOKEN_URL = f"{OPENAI_AUTH}/oauth/token"
OAUTH_REDIRECT_URI = "https://chatgpt.com/api/auth/callback/openai"
OAUTH_SCOPE = "openid email profile offline_access model.request model.read organization.read organization.write"

# Token retrieval uses Codex CLI client (public client, supports PKCE)
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_REDIRECT_URI = "http://localhost:1455/auth/callback"
CODEX_SCOPE = "openid email profile offline_access"

# Sentinel (PoW protection) - version numbers may change with OpenAI updates (supports override via environment variables)
SENTINEL_BASE = os.environ.get("SENTINEL_BASE_URL", "https://sentinel.openai.com")
SENTINEL_SDK_VERSION = os.environ.get("SENTINEL_SDK_VERSION", "20260124ceb8")
SENTINEL_FRAME_VERSION = os.environ.get("SENTINEL_FRAME_VERSION", "20260219f9f6")
SENTINEL_SDK_URL = f"{SENTINEL_BASE}/sentinel/{SENTINEL_SDK_VERSION}/sdk.js"
SENTINEL_REQ_URL = f"{SENTINEL_BASE}/backend-api/sentinel/req"
SENTINEL_FRAME_URL = f"{SENTINEL_BASE}/backend-api/sentinel/frame.html?sv={SENTINEL_FRAME_VERSION}"

# OAuth consent page form selector
OAUTH_CONSENT_FORM_SELECTOR = 'form[action*="/sign-in-with-chatgpt/"][action*="/consent"]'

# OpenAI API endpoints
OPENAI_API_ENDPOINTS = {
    "sentinel": SENTINEL_REQ_URL,
    "signup": f"{OPENAI_AUTH}/api/accounts/authorize/continue",
    "register": f"{OPENAI_AUTH}/api/accounts/user/register",
    "send_otp": f"{OPENAI_AUTH}/api/accounts/email-otp/send",
    "validate_otp": f"{OPENAI_AUTH}/api/accounts/email-otp/validate",
    "create_account": f"{OPENAI_AUTH}/api/accounts/create_account",
    "select_workspace": f"{OPENAI_AUTH}/api/accounts/workspace/select",
}

# OpenAI page types (used to determine account status)
OPENAI_PAGE_TYPES = {
    "EMAIL_OTP_VERIFICATION": "email_otp_verification",  # Registered account, requires OTP verification
    "PASSWORD_REGISTRATION": "password",  # New account, needs password setup
}

# ============================================================================
# Email service related constants
# ============================================================================

# Tempmail.lol API endpoints
TEMPMAIL_API_ENDPOINTS = {
    "create_inbox": "/inbox/create",
    "get_inbox": "/inbox",
}

# Custom domain email API endpoints
CUSTOM_DOMAIN_API_ENDPOINTS = {
    "get_config": "/api/config",
    "create_email": "/api/emails/generate",
    "list_emails": "/api/emails",
    "get_email_messages": "/api/emails/{emailId}",
    "delete_email": "/api/emails/{emailId}",
    "get_message": "/api/emails/{emailId}/{messageId}",
}

# Email service default configuration
EMAIL_SERVICE_DEFAULTS = {
    "tempmail": {
        "base_url": "https://api.tempmail.lol/v2",
        "timeout": 30,
        "max_retries": 3,
    },
    "outlook": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
        "smtp_server": "smtp.office365.com",
        "smtp_port": 587,
        "timeout": 30,
    },
    "custom_domain": {
        "base_url": "",  # Requires user configuration
        "api_key_header": "X-API-Key",
        "timeout": 30,
        "max_retries": 3,
    }
}

# ============================================================================
# Registration flow related constants
# ============================================================================

# OTP code related
OTP_CODE_PATTERN = r"(?<!\d)(\d{6})(?!\d)"
OTP_MAX_ATTEMPTS = 40  # Maximum polling attempts

# OTP code extraction regex (enhanced version)
# Simple match: any 6-digit number
OTP_CODE_SIMPLE_PATTERN = r"(?<!\d)(\d{6})(?!\d)"
# Semantic match: OTP with context (e.g. "code is 123456", "verification code 123456")
OTP_CODE_SEMANTIC_PATTERN = r'(?:code\s+is|verification\s*code[=:]\s*)(\d{6})'

# OpenAI verification email senders
OPENAI_EMAIL_SENDERS = [
    "noreply@openai.com",
    "no-reply@openai.com",
    "@openai.com",     # Exact domain match
    ".openai.com",     # Subdomain match (e.g. otp@tm1.openai.com)
]

# OpenAI verification email keywords
OPENAI_VERIFICATION_KEYWORDS = [
    "verify your email",
    "verification code",
    "verification code",
    "your openai code",
    "code is",
    "one-time code",
]

# Password generation
PASSWORD_CHARSET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
DEFAULT_PASSWORD_LENGTH = 12

# User info generation (for registration)

# Common English first names
FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles",
    "Emma", "Olivia", "Ava", "Isabella", "Sophia", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn", "Skyler",
    "Liam", "Noah", "Ethan", "Lucas", "Mason", "Oliver", "Elijah", "Aiden", "Henry", "Sebastian",
    "Grace", "Lily", "Chloe", "Zoey", "Nora", "Aria", "Hazel", "Aurora", "Stella", "Ivy"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores"
]

def generate_random_user_info() -> dict:
    """
    Generate random user information

    Returns:
        Dictionary containing name and birthdate
    """
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    name = f"{first_name} {last_name}"

    # Generate random birthday (age 25-40, avoiding boundary age issues)
    current_year = datetime.now().year
    birth_year = random.randint(current_year - 40, current_year - 25)
    birth_month = random.randint(1, 12)
    # Determine days based on month
    if birth_month in [1, 3, 5, 7, 8, 10, 12]:
        birth_day = random.randint(1, 31)
    elif birth_month in [4, 6, 9, 11]:
        birth_day = random.randint(1, 30)
    else:
        # February, simplified handling
        birth_day = random.randint(1, 28)

    birthdate = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"

    return {
        "name": name,
        "birthdate": birthdate
    }

# Keep default values for compatibility
DEFAULT_USER_INFO = {
    "name": "Neo",
    "birthdate": "2000-02-20",
}

# ============================================================================
# Proxy related constants
# ============================================================================

PROXY_TYPES = ["http", "socks5", "socks5h"]
DEFAULT_PROXY_CONFIG = {
    "enabled": False,
    "type": "http",
    "host": "127.0.0.1",
    "port": 7890,
}

# ============================================================================
# Database related constants
# ============================================================================

# Database table names
DB_TABLE_NAMES = {
    "accounts": "accounts",
    "email_services": "email_services",
    "registration_tasks": "registration_tasks",
    "settings": "settings",
}

# Default settings
DEFAULT_SETTINGS = [
    # (key, value, description, category)
    ("system.name", APP_NAME, "System name", "general"),
    ("system.version", APP_VERSION, "System version", "general"),
    ("logs.retention_days", "30", "Log retention days", "general"),
    ("openai.client_id", OAUTH_CLIENT_ID, "OpenAI OAuth Client ID", "openai"),
    ("openai.auth_url", OAUTH_AUTH_URL, "OpenAI Auth URL", "openai"),
    ("openai.token_url", OAUTH_TOKEN_URL, "OpenAI Token URL", "openai"),
    ("openai.redirect_uri", OAUTH_REDIRECT_URI, "OpenAI Callback URL", "openai"),
    ("openai.scope", OAUTH_SCOPE, "OpenAI Permission Scope", "openai"),
    ("proxy.enabled", "false", "Enable proxy", "proxy"),
    ("proxy.type", "http", "Proxy type (http/socks5)", "proxy"),
    ("proxy.host", "127.0.0.1", "Proxy host", "proxy"),
    ("proxy.port", "7890", "Proxy port", "proxy"),
    ("registration.max_retries", "3", "Maximum retries", "registration"),
    ("registration.timeout", "120", "Timeout (seconds)", "registration"),
    ("registration.default_password_length", "12", "Default password length", "registration"),
    ("webui.host", "0.0.0.0", "Web UI listen host", "webui"),
    ("webui.port", "8000", "Web UI listen port", "webui"),
    ("webui.debug", "true", "Debug mode", "webui"),
]

# ============================================================================
# Web UI related constants
# ============================================================================

# WebSocket events
WEBSOCKET_EVENTS = {
    "CONNECT": "connect",
    "DISCONNECT": "disconnect",
    "LOG": "log",
    "STATUS": "status",
    "ERROR": "error",
    "COMPLETE": "complete",
}

# API response status codes
API_STATUS_CODES = {
    "SUCCESS": 200,
    "CREATED": 201,
    "BAD_REQUEST": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "INTERNAL_ERROR": 500,
}

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# ============================================================================
# Error messages
# ============================================================================

ERROR_MESSAGES = {
    # General errors
    "DATABASE_ERROR": "Database operation failed",
    "CONFIG_ERROR": "Configuration error",
    "NETWORK_ERROR": "Network connection failed",
    "TIMEOUT": "Operation timed out",
    "VALIDATION_ERROR": "Parameter validation failed",

    # Email service errors
    "EMAIL_SERVICE_UNAVAILABLE": "Email service unavailable",
    "EMAIL_CREATION_FAILED": "Failed to create email",
    "OTP_NOT_RECEIVED": "OTP code not received",
    "OTP_INVALID": "OTP code is invalid",

    # OpenAI related errors
    "OPENAI_AUTH_FAILED": "OpenAI authentication failed",
    "OPENAI_RATE_LIMIT": "OpenAI API rate limited",
    "OPENAI_CAPTCHA": "CAPTCHA encountered",

    # Proxy errors
    "PROXY_FAILED": "Proxy connection failed",
    "PROXY_AUTH_FAILED": "Proxy authentication failed",

    # Account errors
    "ACCOUNT_NOT_FOUND": "Account not found",
    "ACCOUNT_ALREADY_EXISTS": "Account already exists",
    "ACCOUNT_INVALID": "Account is invalid",

    # Task errors
    "TASK_NOT_FOUND": "Task not found",
    "TASK_ALREADY_RUNNING": "Task is already running",
    "TASK_CANCELLED": "Task has been cancelled",
}

# ============================================================================
# Regular expressions
# ============================================================================

REGEX_PATTERNS = {
    "EMAIL": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    "URL": r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+",
    "IP_ADDRESS": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "OTP_CODE": OTP_CODE_PATTERN,
}

# ============================================================================
# Time constants
# ============================================================================

TIME_CONSTANTS = {
    "SECOND": 1,
    "MINUTE": 60,
    "HOUR": 3600,
    "DAY": 86400,
    "WEEK": 604800,
}


# ============================================================================
# Microsoft/Outlook related constants
# ============================================================================

# Microsoft OAuth2 Token endpoints
MICROSOFT_TOKEN_ENDPOINTS = {
    # Legacy IMAP endpoint
    "LIVE": "https://login.live.com/oauth20_token.srf",
    # New IMAP endpoint (requires specific scope)
    "CONSUMERS": "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
    # Graph API endpoint
    "COMMON": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
}

# IMAP server configuration
OUTLOOK_IMAP_SERVERS = {
    "OLD": "outlook.office365.com",  # Legacy IMAP
    "NEW": "outlook.live.com",       # New IMAP
}

# Microsoft OAuth2 Scopes
MICROSOFT_SCOPES = {
    # Legacy IMAP does not require specific scope
    "IMAP_OLD": "",
    # Scope required for new IMAP
    "IMAP_NEW": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    # Scope required for Graph API
    "GRAPH_API": "https://graph.microsoft.com/.default",
}

# Outlook provider default priority
OUTLOOK_PROVIDER_PRIORITY = ["imap_new", "imap_old", "graph_api"]
