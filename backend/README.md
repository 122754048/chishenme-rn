# ChiShenMe Backend (Python + FastAPI + Alipay skeleton)

This is a backend skeleton for:
- membership plans (`free` / `pro` / `family`)
- daily quota enforcement (server-side authority)
- Alipay order creation + callback activation flow
- JWT auth + SQLite persistence + idempotency key support

## Run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# required for production:
# export APP_ENV=production
# export JWT_SECRET=...
# export ALIPAY_NOTIFY_TOKEN=...
# export ALIPAY_PUBLIC_KEY=...
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET /health`
- `GET /plans`
- `POST /auth/register`
- `POST /auth/login`
- `GET /membership/me`
- `GET /quota/today`
- `POST /quota/consume`
- `POST /billing/alipay/create-order`
- `GET /billing/orders/{order_no}`
- `POST /billing/alipay/notify`

## Run tests

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_api
```

## Important production TODO

1. Replace SQLite with PostgreSQL + Redis distributed idempotency/locks.
2. Replace temporary `alipay_notify_token` check with full Alipay RSA2 signature verification.
3. Add richer order state machine (refund/close) and reconciliation jobs.
4. Add rate limiting, audit logs, and secret rotation policy.

## Frontend integration env

- `EXPO_PUBLIC_API_BASE_URL` backend URL
- `EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD` temporary bootstrap password for development-only auto register/login
