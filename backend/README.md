# ChiShenMe Backend (Python + FastAPI + Payments)

This backend provides:
- membership plans (`free` / `pro` / `family`)
- daily quota enforcement (server-side authority)
- Alipay order creation + RSA2-verified callback activation flow for non-iOS payment use cases
- RevenueCat webhook entitlement sync for iOS Apple IAP subscriptions
- account deletion for App Store compliance
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
# export ALIPAY_APP_ID=...
# export ALIPAY_PUBLIC_KEY=...
# export REVENUECAT_WEBHOOK_SECRET=...
# export REVENUECAT_PRO_PRODUCT_ID=...
# export REVENUECAT_FAMILY_PRODUCT_ID=...
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
- `POST /billing/revenuecat/webhook`
- `DELETE /account/me`

## Run tests

```bash
cd backend
PYTHONPATH=. python -m unittest discover -s tests -v
```

## Production notes

- `APP_ENV=production` refuses placeholder `JWT_SECRET`, `ALIPAY_APP_ID`, `ALIPAY_PUBLIC_KEY`, `REVENUECAT_WEBHOOK_SECRET`, and RevenueCat product ID values at startup.
- Alipay notifications are verified with RSA2 over the raw JSON/form parameters before membership activation.
- iOS digital membership commercialization should use Apple IAP via RevenueCat. Do not expose Alipay as the iOS digital membership purchase method.
- RevenueCat webhooks must be configured with the backend `/billing/revenuecat/webhook` URL and a shared bearer secret.
- Account deletion removes the generated user record and associated local backend data rows.
- Passwords are stored with salted PBKDF2-SHA256 hashes; legacy SHA-256 hashes still verify for migration safety.
- SQLite is suitable for the current single-instance deployment profile. Move to PostgreSQL and a distributed idempotency store before running multiple backend instances.
- Add reconciliation jobs, richer refund/close states, centralized audit logs, and secret rotation as operational hardening when payment volume grows.

## Frontend integration env

- `EXPO_PUBLIC_API_BASE_URL` backend URL
- `EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD` temporary bootstrap password for development-only auto register/login
- `EXPO_PUBLIC_RC_IOS_API_KEY` RevenueCat iOS public SDK key
- `EXPO_PUBLIC_RC_ENTITLEMENT_ID` RevenueCat entitlement id, expected default `premium`
- `EXPO_PUBLIC_RC_PRO_PRODUCT_ID` Pro subscription product id
- `EXPO_PUBLIC_RC_FAMILY_PRODUCT_ID` Family subscription product id
