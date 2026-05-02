# Customer Portal API

A standalone customer-facing / admin backend service that reuses the existing platform registration core, platform metadata, task runtime, account assets, proxy management, and system capabilities from this repository.

## Implemented Capabilities

- Authentication: login, token refresh, logout, current user
- User endpoints:
  - `GET /api/app/platforms`
  - `GET /api/app/config/options`
  - `GET /api/app/products`
  - `POST /api/app/tasks/register`
  - `GET /api/app/tasks`
  - `GET /api/app/tasks/{task_id}`
  - `GET /api/app/tasks/{task_id}/events`
  - `GET /api/app/tasks/{task_id}/logs/stream`
  - `GET /api/app/orders`
  - `POST /api/app/orders`
  - `GET /api/app/orders/{order_no}`
  - `POST /api/app/payments/{order_no}/submit`
  - `GET /api/app/subscriptions`
  - `GET /api/app/profile`
  - `PATCH /api/app/profile`
- Admin endpoints:
  - Users, roles, permissions, platform authorization, product catalog
  - Platforms, configuration, registration tasks, task queries, task logs
  - Accounts, platform actions, proxies, Solver status
- Payment endpoints:
  - `POST /api/payment/callback/{channel_code}`

## Directory

```text
customer_portal_api/
├── app/
│   ├── routers/
│   ├── services/
│   ├── bootstrap.py
│   ├── config.py
│   ├── db.py
│   ├── deps.py
│   ├── models.py
│   └── security.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── main.py
```

## Local Setup

### 1. Install dependencies

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or install only the portal dependencies:

```bash
pip install -r customer_portal_api/requirements.txt
```

### 2. Configure environment variables

Copy the environment template:

```bash
cp customer_portal_api/.env.example customer_portal_api/.env
```

Common variables:

- `PORTAL_JWT_SECRET`
- `PORTAL_ADMIN_USERNAME`
- `PORTAL_ADMIN_PASSWORD`
- `PORTAL_ADMIN_EMAIL`
- `PORTAL_START_SOLVER`
- `ACCOUNT_MANAGER_DATABASE_URL`

### 3. Start the service

From the repository root:

```bash
source .venv/bin/activate
export $(grep -v '^#' customer_portal_api/.env | xargs)
python -m uvicorn customer_portal_api.main:app --host 0.0.0.0 --port 8100 --reload
```

API documentation:

- Swagger UI: `http://127.0.0.1:8100/docs`
- OpenAPI JSON: `http://127.0.0.1:8100/openapi.json`

Default admin credentials:

- Username: `admin`
- Password: `admin123456`

The admin account is automatically created on first startup.

## Docker Deployment

From the repository root:

```bash
docker compose -f customer_portal_api/docker-compose.yml up --build
```

The service listens on:

- `http://127.0.0.1:8100`

## Design Notes

- The project reuses the existing platform registration and task execution core — no reimplementation of platform plugin logic
- Its own user tables, token refresh, platform authorization, orders, subscriptions, and task ownership tables share the same SQLite database with existing business tables
- User registration endpoints create real registration tasks, with task ownership tables restricting users to see only their own tasks
- The payment pipeline includes product seeding, order creation, payment submission, payment callbacks, subscription activation, and platform registration permission activation
