# AIT Auto Register

<p align="center">
  <a href="https://github.com/lieusonsg/AIT-Auto-Register/stargazers"><img src="https://img.shields.io/github/stars/lieusonsg/AIT-Auto-Register?style=for-the-badge&logo=github&color=FFB003" alt="Stars" /></a>
  <a href="https://github.com/lieusonsg/AIT-Auto-Register/network/members"><img src="https://img.shields.io/github/forks/lieusonsg/AIT-Auto-Register?style=for-the-badge&logo=github&color=blue" alt="Forks" /></a>
  <a href="https://github.com/lieusonsg/AIT-Auto-Register/releases"><img src="https://img.shields.io/github/v/release/lieusonsg/AIT-Auto-Register?style=for-the-badge&logo=github&color=green" alt="Release" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/lieusonsg/AIT-Auto-Register?style=for-the-badge&color=orange" alt="License" /></a>
</p>

<p align="center">
  <b>English</b> |
  <a href="README_vi.md">Tiếng Việt</a>
</p>

<p align="center">
  <b>Auto-register accounts for ChatGPT, Cursor, Kiro, Grok, Windsurf, Trae & 13+ AI platforms · Protocol/browser dual-mode · Plugin-based · One-click Mac/Windows desktop</b>
</p>

<a href="https://bestproxy.com/?keyword=l85nsbgw" target="_blank"><img src="assets/bestproxy.gif" alt="BestProxy - High-purity residential IPs with one-account-per-IP isolation, full-link anti-correlation, significantly boosting account approval rates and long-term survival" width="100%"></a>

> ⚠️ **Disclaimer**: This project is for learning and research purposes only. It must not be used for any commercial purposes. Users are solely responsible for any consequences arising from the use of this project.

A multi-platform account auto-registration and management system with plugin-based extensibility and a built-in Web UI.

<a href="https://legionproxy.io/?utm_source=github&utm_campaign=any-auto-register" target="_blank"><img src="assets/legionproxy.png" alt="LegionProxy - Residential proxies built for account registration and automation, 74M+ real residential IPs, 195+ countries, HTTP/3 high-speed connection, starting at $0.60/GB" width="100%"></a>

[LegionProxy — Residential proxies built for account registration and automation · 74M+ real residential IPs · 195+ countries · HTTP/3 · From $0.60/GB](https://legionproxy.io/?utm_source=github&utm_campaign=any-auto-register)

## Table of Contents

- [Highlights](#highlights)
- [Features](#features)
- [Screenshots](#screenshots)
- [Tech Stack](#tech-stack)
- [Desktop Download](#desktop-download)
- [Quick Start](#quick-start)
- [Docker Deployment](#docker-deployment)
- [Mailbox Providers](#mailbox-providers)
- [Captcha Providers](#captcha-providers)
- [Proxy Pool](#proxy-pool)
- [SMS Providers](#sms-providers)
- [Account Lifecycle](#account-lifecycle)
- [Stats Dashboard](#stats-dashboard)
- [Any2API Integration](#any2api-integration)
- [Plugin Development](#plugin-development)
- [FAQ](#faq)
- [Sponsors](#sponsors)
- [Community](#community)
- [Star History](#star-history)
- [License](#license)

## Highlights

Why choose AIT Auto Register over alternatives:

| Capability | AIT Auto Register | Other tools |
|------|------|------|
| 🖥️ **One-click desktop app** | ✅ Mac / Windows Electron client, no CLI required | ❌ Usually CLI / Docker only |
| 🧩 **Platform coverage** | ✅ 13+ platforms out-of-the-box + generic Anything adapter | Usually 1-3 platforms |
| 📨 **Mailbox services** | ✅ 9 services (self-hosted + public + DDG) | Usually 1-2 |
| ⚡ **Three execution modes** | ✅ Pure protocol (no browser, fastest) / headless / headed | Usually browser-only |
| 🔁 **Account lifecycle** | ✅ Validity check, token auto-refresh, trial expiration warning | ❌ Most only register |
| 📊 **Success-rate dashboard** | ✅ Per-platform / per-proxy / per-day stats, error aggregation | ❌ |
| 🔌 **Any2API integration** | ✅ Register-and-use, auto-push to gateway | ❌ |
| 📦 **Plugin architecture** | ✅ Platform / mailbox / captcha / SMS / proxy all pluggable | Usually hardcoded |

> 💡 Combine [`Any2API`](https://github.com/lxf746/any2api) gateway + `AIT Auto Register` to enable a full pipeline: **bulk-register accounts → auto-push to gateway → instantly use as OpenAI/Claude-compatible API**.

## Features

- **Multi-platform**: ChatGPT, Cursor, Kiro, Trae.ai, Tavily, Grok, Blink, Cerebras, OpenBlockLabs, Windsurf, plus a generic Anything adapter for custom plugins
- **Multi-mailbox**: MoeMail (self-hosted), Laoudo, DuckMail, Testmail, Cloudflare Worker self-hosted, Freemail, TempMail.lol, Temp-Mail Web, DuckDuckGo Email
- **Multi-mode execution**: API protocol (no browser) / headless browser / headed browser (per-platform support)
- **Captcha**: YesCaptcha, 2Captcha, local Solver (Camoufox)
- **SMS**: SMS-Activate, HeroSMS (for platforms requiring phone verification)
- **Proxy pool**: static round-robin + dynamic API extraction + rotating gateway, success-rate weighting, auto-disable failed proxies
- **Account lifecycle**: scheduled validity checks, automatic token refresh, trial expiration warnings
- **Success-rate dashboard**: stats by platform, day, and proxy; error aggregation
- **Concurrent registration**: configurable concurrency
- **Real-time logs**: SSE streaming to frontend
- **Account export**: JSON, CSV, CPA, Sub2API, Kiro-Go, Any2API formats
- **Any2API sync**: auto-push registered accounts to Any2API gateway, ready to use immediately
- **Per-platform actions**: customizable actions like Kiro account switching, Trae Pro upgrade-link generation

## Screenshots

> 📸 *Screenshots will be updated with each release. For a full demo, try the [Desktop Download](#desktop-download).*

### Dashboard
![Dashboard](assets/screenshots/dashboard.png)

### Registration Task
![Registration Task](assets/screenshots/register-task.png)

### Settings
![Settings](assets/screenshots/settings.png)

### Accounts
![Accounts](assets/screenshots/accounts.png)

## Tech Stack

| Layer | Technology |
|------|------|
| Backend | FastAPI + SQLite (SQLModel) |
| Frontend | React + TypeScript + Vite + TailwindCSS |
| HTTP | curl_cffi (browser fingerprint spoofing) |
| Browser automation | Playwright / Camoufox |

## Desktop Download

> 🚀 **Zero-config one-click**: Skip Python and Node.js — just download the desktop client and double-click.

| Platform | Download |
|------|------|
| 🍎 macOS (Intel / Apple Silicon) | [Get `.dmg` from Releases](https://github.com/lieusonsg/AIT-Auto-Register/releases/latest) |
| 🪟 Windows | [Get `.exe` from Releases](https://github.com/lieusonsg/AIT-Auto-Register/releases/latest) |

The desktop client bundles the full Python backend + React frontend via Electron — works out of the box. Each new version (`v*` tag) is auto-built and published to [Releases](https://github.com/lieusonsg/AIT-Auto-Register/releases).

## Quick Start

### Requirements

- Python 3.11+
- Node.js 18+

### Install

#### macOS / Linux

```bash
git clone https://github.com/lieusonsg/AIT-Auto-Register.git
cd AIT-Auto-Register

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cd frontend && npm install && npm run build && cd ..
```

#### Windows

```bat
git clone https://github.com/lieusonsg/AIT-Auto-Register.git
cd AIT-Auto-Register

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

cd frontend
npm install
npm run build
cd ..
```

### Install browsers (optional, required for headless/headed modes)

```bash
python3 -m playwright install chromium
python3 -m camoufox fetch
```

### Run

```bash
.venv/bin/python3 -m uvicorn main:app --port 8000
```

Open `http://localhost:8000` in your browser.

Notes:

- The entry point is `main:app`
- Backend API endpoints are at `/api/*`
- In production mode, the frontend build output is served by the backend — visit `http://localhost:8000`
- In development mode, the frontend runs independently at `http://localhost:5173` with Vite proxying API requests
- For frontend-backend API contract, see [docs/frontend-api-contract.md](docs/frontend-api-contract.md)
- For the customer portal / admin API, see [customer_portal_api/README.md](customer_portal_api/README.md)

### Development mode (frontend hot-reload)

```bash
cd frontend
npm run dev
# Visit http://localhost:5173
```

## Docker Deployment

### Option 1: Pre-built image (recommended)

```bash
# Create directory
mkdir -p ait-auto-register && cd ait-auto-register

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  app:
    image: ghcr.io/lieusonsg/ait-auto-register:latest
    ports:
      - "8000:8000"   # Web UI
      - "6080:6080"   # noVNC visual browser
      - "8889:8889"   # Turnstile Solver
    environment:
      - DISPLAY=:99
      # - APP_PASSWORD=changeme  # Optional: set access password
    volumes:
      - ./data:/app/data   # Persist database
    restart: unless-stopped
EOF

# Start
docker compose up -d
```

### Option 2: Build from source

```bash
git clone https://github.com/lieusonsg/AIT-Auto-Register.git
cd AIT-Auto-Register
docker compose up -d --build
```

### Access URLs

| Service | URL | Description |
|------|------|------|
| Web UI | `http://localhost:8000` | Main interface |
| noVNC | `http://localhost:6080/vnc.html` | Visual browser (headed mode) |
| Solver | `http://localhost:8889` | Turnstile captcha solver |

> When deploying on a cloud server, ensure ports 8000, 6080, and 8889 are open in the security group / firewall.

### Common commands

```bash
# View logs
docker compose logs -f

# Restart
docker compose restart

# Update to latest version
docker compose pull && docker compose up -d

# Stop
docker compose down
```

## Mailbox Providers

Pick a mailbox service to receive verification codes. All providers are managed via the **Settings → Providers** page in the Web UI.

- **MoeMail** (recommended): self-hosted on Cloudflare via [cloudflare_temp_email](https://github.com/dreamhunter2333/cloudflare_temp_email)
- **Laoudo**: stable custom-domain mailboxes
- **Cloudflare Worker self-hosted**: full control, deploy your own
- **DuckMail / TempMail.lol / Temp-Mail Web**: public temp-mail services
- **DuckDuckGo Email**: `@duck.com` aliases via DDG Email Protection (requires forwarding IMAP)
- **Freemail**: Cloudflare Worker-based, supports admin token + username/password auth
- **Testmail**: `testmail.app` namespace mode, ideal for concurrent tasks

Detailed field references are available in the Web UI's provider editor.

## Captcha Providers

| Service | Notes |
|------|------|
| YesCaptcha | Sign up at [yescaptcha.com](https://yescaptcha.com) for a Client Key |
| 2Captcha | Sign up at [2captcha.com](https://2captcha.com) for an API Key |
| Local Solver | Uses Camoufox locally, run `python3 -m camoufox fetch` first |

## Proxy Pool

The system supports both static and dynamic proxies:

- **Static proxies**: managed in the Proxy page; weighted by success rate; auto-disabled after 5 consecutive failures
- **Dynamic proxies**: API-extraction or rotating-gateway providers (BrightData, Oxylabs, IPRoyal, etc.); falls back to static pool on failure

## SMS Providers

For platforms requiring phone verification (e.g., Cursor):

| Service | Notes |
|------|------|
| SMS-Activate | API key + default country |
| HeroSMS | API key + service code, country ID, max price, number reuse policy |

## Account Lifecycle

Built-in background lifecycle manager runs:

- **Validity check** every 6h — invalid accounts marked
- **Token refresh** every 12h — auto-refreshes expiring tokens (currently ChatGPT)
- **Trial warning** — flags accounts nearing expiration

Manual triggers:

- `POST /api/lifecycle/check` — manual validity check
- `POST /api/lifecycle/refresh` — manual token refresh
- `POST /api/lifecycle/warn` — manual trial warning
- `GET /api/lifecycle/status` — manager status

## Stats Dashboard

Query registration stats via API:

- `GET /api/stats/overview` — global overview
- `GET /api/stats/by-platform` — per-platform success rate
- `GET /api/stats/by-day?days=30` — daily trends
- `GET /api/stats/by-proxy` — proxy success ranking
- `GET /api/stats/errors?days=7` — error aggregation

## Any2API Integration

Pair with [Any2API](https://github.com/lxf746/any2api) — registered accounts are auto-pushed to the gateway, ready to use immediately as OpenAI/Claude-compatible APIs.

Configure in Settings:

| Field | Description |
|------|------|
| `any2api_url` | Any2API instance URL, e.g. `http://localhost:8099` |
| `any2api_password` | Any2API admin password |

Push targets per platform: Kiro → `kiroAccounts`, Grok → `grokTokens`, Cursor → `cursorConfig`, ChatGPT → `chatgptConfig`, Blink → `blinkConfig`, Windsurf → `windsurfAccounts`.

If `any2api_url` is not set, this integration is silently skipped.

## Plugin Development

Adding a new platform:

### 1. Create platform directory

Create a directory under `platforms/` with `__init__.py` and `plugin.py`:

```
platforms/myplatform/
├── __init__.py
├── plugin.py              # Platform adapter (required)
├── protocol_mailbox.py    # Protocol mode registration logic (optional)
├── browser_register.py    # Browser registration logic (optional)
└── browser_oauth.py       # Browser OAuth logic (optional)
```

### 2. Implement plugin.py

```python
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registration import ProtocolMailboxAdapter, OtpSpec, RegistrationResult
from core.registry import register


@register
class MyPlatform(BasePlatform):
    name = "myplatform"
    display_name = "My Platform"
    version = "1.0.0"

    def __init__(self, config: RegisterConfig = None, mailbox: BaseMailbox = None):
        super().__init__(config)
        self.mailbox = mailbox

    def build_protocol_mailbox_adapter(self):
        return ProtocolMailboxAdapter(
            result_mapper=lambda ctx, result: RegistrationResult(
                email=result["email"],
                password=result.get("password", ""),
                status=AccountStatus.REGISTERED,
            ),
            worker_builder=lambda ctx, artifacts: __import__(
                "platforms.myplatform.protocol_mailbox",
                fromlist=["MyWorker"],
            ).MyWorker(proxy=ctx.proxy, log_fn=ctx.log),
            register_runner=lambda worker, ctx, artifacts: worker.run(
                email=ctx.identity.email,
                password=ctx.password,
                otp_callback=artifacts.otp_callback,
            ),
            otp_spec=OtpSpec(wait_message="Waiting for verification email..."),
        )

    def check_valid(self, account: Account) -> bool:
        return bool(account.token)
```

### 3. Declare platform capabilities

```python
class MyPlatform(BasePlatform):
    supported_executors = ["protocol"]
    supported_identity_modes = ["mailbox"]
    supported_oauth_providers = []
    capabilities = []
```

The platform auto-loads on startup.

## Project Structure

```
AIT-Auto-Register/
├── main.py                 # FastAPI entry point
├── Dockerfile              # Docker build
├── docker-compose.yml      # Docker Compose orchestration
├── requirements.txt        # Python dependencies
├── api/                    # HTTP route layer
├── application/            # Application service layer
├── domain/                 # Domain models
├── infrastructure/         # Repository and runtime adapters
├── core/                   # Core capabilities
├── platforms/              # Platform plugins
├── providers/              # Provider plugins (mailbox / captcha / SMS / proxy)
├── services/               # Background services
├── customer_portal_api/    # Customer portal / admin API
├── electron/               # Electron desktop packaging
├── tests/                  # Tests
└── frontend/               # React frontend
```

## FAQ

### Captcha keeps failing?

1. Verify your captcha provider is configured correctly (YesCaptcha Client Key or local Solver)
2. In protocol mode, prefer remote captcha services (YesCaptcha / 2Captcha)
3. In browser mode, Camoufox tries the Turnstile checkbox first and falls back to remote solvers
4. If failures persist, check proxy IP quality — high-risk IPs trigger stricter challenges

### Proxies getting banned / low success rate?

1. Check per-proxy stats in the Proxy page and disable low-performers
2. Use residential proxies over datacenter IPs — significantly higher pass rate
3. Lower concurrency to avoid too many requests from the same IP in a short time
4. Different platforms have different IP sensitivity — consider per-platform proxy pools

### Browser mode setup?

```bash
# Install Playwright browser
python3 -m playwright install chromium

# Install Camoufox (anti-fingerprint browser)
python3 -m camoufox fetch
```

### Solver startup timeout?

`[Solver] startup timeout` means the local Turnstile Solver failed the health check within 30 seconds. The main service will still start. Common causes: first launch needs to download/initialize Camoufox, missing browser dependencies, or port 8889 is in use.

Resolution:

1. Run `python3 -m camoufox fetch` first, then click "Restart Solver" in the Settings page
2. If you don't need the local Solver, configure YesCaptcha or 2Captcha and select a remote captcha service for registration tasks
3. In Docker, use the pre-built image; for local bare-metal, check port 8889 and Camoufox installation

## Contributing

Issues and Pull Requests are welcome.

1. Fork this repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit changes: `git commit -m 'feat: add my feature'`
4. Push branch: `git push origin feature/my-feature`
5. Submit a Pull Request

Commit conventions follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `refactor:` refactoring
- `test:` tests

## Changelog

See [GitHub Releases](https://github.com/lieusonsg/AIT-Auto-Register/releases).

## Sponsors

Thanks to the following sponsors for their long-term support. If your service targets account registration, automation, or AI developers, feel free to reach out.

| Logo | Name | Description | Link |
| --- | --- | --- | --- |
| <a href="https://bestproxy.com/?keyword=l85nsbgw" target="_blank"><img src="assets/bestproxy.gif" alt="BestProxy" width="140" /></a> | **BestProxy** | High-purity residential IPs with one-account-per-IP isolation, full-link anti-correlation, significantly boosting approval rates and long-term survival. | [bestproxy.com](https://bestproxy.com/?keyword=l85nsbgw) |
| <a href="https://legionproxy.io/?utm_source=github&utm_campaign=any-auto-register" target="_blank"><img src="assets/legionproxy.png" alt="LegionProxy" width="140" /></a> | **LegionProxy** | Residential proxies built for account registration and automation, 74M+ real residential IPs, 195+ countries, HTTP/3 high-speed connection, from $0.60/GB. | [legionproxy.io](https://legionproxy.io/?utm_source=github&utm_campaign=any-auto-register) |

## Community

Join the user group for updates, configuration tips, and registration know-how.

For bugs and feature requests, please use [Issues](https://github.com/lieusonsg/AIT-Auto-Register/issues).

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=lieusonsg/AIT-Auto-Register&type=Date)](https://star-history.com/#lieusonsg/AIT-Auto-Register&Date)

## License

This project is licensed under [AGPL-3.0](LICENSE). Personal learning and research are unrestricted; commercial use must comply with AGPL-3.0 (derivative works must be open-sourced).
