import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Header, Depends, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import PlainTextResponse

from .config import settings
from .db import init_db, tx, utc_now_iso
from .schemas import (
    Plan,
    QuotaResponse,
    QuotaConsumeRequest,
    QuotaConsumeResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderStatusResponse,
    AlipayNotifyPayload,
    MembershipResponse,
    AuthRequest,
    AuthResponse,
    AccountDeletionResponse,
    NearbyRestaurantsRequest,
    NearbyRestaurantsResponse,
    MenuScanResponse,
)
from .security import hash_password, verify_password, create_access_token, decode_access_token
from .services.alipay import verify_alipay_rsa2_signature
from .services.discovery import search_nearby_restaurants, scan_menu_image

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.assert_runtime_safe()
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail='missing bearer token')
    token = authorization.split(' ', 1)[1].strip()
    try:
        user_id = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    with tx() as conn:
        exists = conn.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=401, detail='user not found')
    return user_id


def _plan_for_user(conn, user_id: str) -> str:
    row = conn.execute('SELECT plan FROM subscriptions WHERE user_id = ?', (user_id,)).fetchone()
    return row['plan'] if row else 'free'


def _membership_for_user(conn, user_id: str) -> dict:
    row = conn.execute(
        'SELECT plan, source, product_id, expires_at, updated_at FROM subscriptions WHERE user_id = ?',
        (user_id,),
    ).fetchone()
    if not row:
        return {
            'user_id': user_id,
            'plan': 'free',
            'source': 'local',
            'product_id': None,
            'expires_at': None,
            'updated_at': datetime.now(UTC),
        }
    return {'user_id': user_id, **dict(row)}


def _plan_from_revenuecat_product(product_id: str | None) -> str | None:
    if product_id == settings.revenuecat_family_product_id:
        return 'family'
    if product_id == settings.revenuecat_pro_product_id:
        return 'pro'
    return None


def _revenuecat_event_is_inactive(event_type: str) -> bool:
    return event_type.upper() in {'EXPIRATION', 'CANCELLATION', 'BILLING_ISSUE', 'TRANSFER'}


def _quota_for_user(conn, user_id: str) -> dict:
    plan = _plan_for_user(conn, user_id)
    today = _today()
    if plan in {'pro', 'family'}:
        return {'date': today, 'left': -1}

    row = conn.execute(
        'SELECT left_count FROM daily_quotas WHERE user_id = ? AND quota_date = ?',
        (user_id, today),
    ).fetchone()
    if row:
        return {'date': today, 'left': max(0, int(row['left_count']))}

    conn.execute(
        'INSERT INTO daily_quotas (user_id, quota_date, left_count) VALUES (?, ?, ?)',
        (user_id, today, settings.free_daily_quota),
    )
    return {'date': today, 'left': settings.free_daily_quota}


def _idempotent_response(conn, user_id: str, endpoint: str, idem_key: str | None):
    if not idem_key:
        return None
    row = conn.execute(
        'SELECT response_json FROM idempotency_keys WHERE user_id = ? AND endpoint = ? AND idem_key = ?',
        (user_id, endpoint, idem_key),
    ).fetchone()
    return json.loads(row['response_json']) if row else None


def _save_idempotent_response(conn, user_id: str, endpoint: str, idem_key: str | None, response_payload: dict):
    if not idem_key:
        return
    conn.execute(
        'INSERT OR REPLACE INTO idempotency_keys (user_id, endpoint, idem_key, response_json, created_at) VALUES (?, ?, ?, ?, ?)',
        (user_id, endpoint, idem_key, json.dumps(response_payload), utc_now_iso()),
    )


@app.get('/health')
def health() -> dict:
    return {'status': 'ok'}


@app.post('/auth/register', response_model=AuthResponse)
@limiter.limit("5/minute")
def register(request: Request, payload: AuthRequest) -> AuthResponse:
    with tx() as conn:
        existed = conn.execute('SELECT 1 FROM users WHERE user_id = ?', (payload.user_id,)).fetchone()
        if existed:
            raise HTTPException(status_code=409, detail='user already exists')

        conn.execute(
            'INSERT INTO users (user_id, password_hash, created_at) VALUES (?, ?, ?)',
            (payload.user_id, hash_password(payload.password), utc_now_iso()),
        )
        conn.execute(
            'INSERT OR IGNORE INTO subscriptions (user_id, plan, source, updated_at) VALUES (?, ?, ?, ?)',
            (payload.user_id, 'free', 'local', utc_now_iso()),
        )

    return AuthResponse(access_token=create_access_token(payload.user_id))


@app.post('/auth/login', response_model=AuthResponse)
@limiter.limit("10/minute")
def login(request: Request, payload: AuthRequest) -> AuthResponse:
    with tx() as conn:
        row = conn.execute('SELECT password_hash FROM users WHERE user_id = ?', (payload.user_id,)).fetchone()
        if not row or not verify_password(payload.password, row['password_hash']):
            raise HTTPException(status_code=401, detail='invalid credentials')
    return AuthResponse(access_token=create_access_token(payload.user_id))


@app.get('/plans', response_model=list[Plan])
def plans() -> list[Plan]:
    return [
        Plan(key='free', title='\u514d\u8d39\u7248', monthly_price_cny=0),
        Plan(key='pro', title='Pro', monthly_price_cny=9.9),
        Plan(key='family', title='\u5bb6\u5ead\u7248', monthly_price_cny=19.9),
    ]


@app.get('/membership/me', response_model=MembershipResponse)
def membership_me(user_id: str = Depends(_current_user)) -> MembershipResponse:
    with tx() as conn:
        membership = _membership_for_user(conn, user_id)
    return MembershipResponse(**membership)


@app.delete('/account/me', response_model=AccountDeletionResponse)
def account_delete(user_id: str = Depends(_current_user)) -> AccountDeletionResponse:
    with tx() as conn:
        conn.execute('DELETE FROM daily_quotas WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM idempotency_keys WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM orders WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    return AccountDeletionResponse(deleted=True)


@app.get('/quota/today', response_model=QuotaResponse)
def quota_today(user_id: str = Depends(_current_user)) -> QuotaResponse:
    with tx() as conn:
        q = _quota_for_user(conn, user_id)
    return QuotaResponse(**q)


@app.post('/discovery/nearby-restaurants', response_model=NearbyRestaurantsResponse)
async def nearby_restaurants(
    payload: NearbyRestaurantsRequest,
    _: str = Depends(_current_user),
) -> NearbyRestaurantsResponse:
    restaurants, source = await search_nearby_restaurants(payload, settings.google_places_api_key)
    return NearbyRestaurantsResponse(restaurants=restaurants, source=source)


@app.post('/discovery/menu-scan', response_model=MenuScanResponse)
async def menu_scan(
    file: UploadFile = File(...),
    cuisines: str = Form(default='[]'),
    restrictions: str = Form(default='[]'),
    restaurant_name: str | None = Form(default=None),
    _: str = Depends(_current_user),
) -> MenuScanResponse:
    try:
        cuisine_list = json.loads(cuisines)
        restriction_list = json.loads(restrictions)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail='invalid menu scan payload') from exc

    file_bytes = await file.read()
    items, source, note = await scan_menu_image(
        file_bytes=file_bytes,
        filename=file.filename or 'menu.jpg',
        cuisines=[item for item in cuisine_list if isinstance(item, str)],
        restrictions=[item for item in restriction_list if isinstance(item, str)],
        restaurant_name=restaurant_name,
        openai_api_key=settings.openai_api_key,
    )
    return MenuScanResponse(items=items, source=source, note=note)


@app.post('/quota/consume', response_model=QuotaConsumeResponse)
def quota_consume(
    _: QuotaConsumeRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    user_id: str = Depends(_current_user),
) -> QuotaConsumeResponse:
    with tx() as conn:
        cached = _idempotent_response(conn, user_id, 'quota.consume', idempotency_key)
        if cached:
            return QuotaConsumeResponse(**cached)

        quota = _quota_for_user(conn, user_id)
        if quota['left'] == -1:
            result = {'allowed': True, **quota}
            _save_idempotent_response(conn, user_id, 'quota.consume', idempotency_key, result)
            return QuotaConsumeResponse(**result)

        if quota['left'] <= 0:
            result = {'allowed': False, **quota}
            _save_idempotent_response(conn, user_id, 'quota.consume', idempotency_key, result)
            return QuotaConsumeResponse(**result)

        next_left = quota['left'] - 1
        conn.execute(
            'UPDATE daily_quotas SET left_count = ? WHERE user_id = ? AND quota_date = ?',
            (next_left, user_id, quota['date']),
        )
        result = {'allowed': True, 'date': quota['date'], 'left': next_left}
        _save_idempotent_response(conn, user_id, 'quota.consume', idempotency_key, result)
        return QuotaConsumeResponse(**result)


@app.post('/billing/alipay/create-order', response_model=OrderCreateResponse)
def alipay_create_order(
    payload: OrderCreateRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    user_id: str = Depends(_current_user),
) -> OrderCreateResponse:
    if payload.plan not in {'pro', 'family'}:
        raise HTTPException(status_code=400, detail='unsupported plan')

    with tx() as conn:
        cached = _idempotent_response(conn, user_id, 'billing.create_order', idempotency_key)
        if cached:
            return OrderCreateResponse(**cached)

        amount = 9.9 if payload.plan == 'pro' else 19.9
        order_no = datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')
        conn.execute(
            'INSERT INTO orders (order_no, user_id, plan, amount, status, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (order_no, user_id, payload.plan, amount, 'created', utc_now_iso()),
        )
        response_payload = {
            'order_no': order_no,
            'status': 'created',
            'pay_url': f'https://openapi.alipay.com/gateway.do?out_trade_no={order_no}',
        }
        _save_idempotent_response(conn, user_id, 'billing.create_order', idempotency_key, response_payload)
        return OrderCreateResponse(**response_payload)


@app.get('/billing/orders/{order_no}', response_model=OrderStatusResponse)
def order_status(order_no: str, user_id: str = Depends(_current_user)) -> OrderStatusResponse:
    with tx() as conn:
        row = conn.execute(
            'SELECT order_no, user_id, plan, amount, status FROM orders WHERE order_no = ? AND user_id = ?',
            (order_no, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='order not found')
        return OrderStatusResponse(**dict(row))


async def _notify_params_from_request(request: Request) -> dict:
    content_type = request.headers.get('content-type', '')
    if 'application/json' in content_type:
        body = await request.json()
        return dict(body)
    form = await request.form()
    return dict(form)


@app.post('/billing/alipay/notify')
async def alipay_notify(request: Request) -> dict:
    notify_params = await _notify_params_from_request(request)
    try:
        payload = AlipayNotifyPayload.model_validate(notify_params)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if payload.app_id != settings.alipay_app_id:
        raise HTTPException(status_code=401, detail='invalid alipay app id')
    if payload.sign_type != 'RSA2':
        raise HTTPException(status_code=400, detail='unsupported alipay sign type')
    if not verify_alipay_rsa2_signature(notify_params, settings.alipay_public_key):
        raise HTTPException(status_code=401, detail='invalid notify signature')

    gmt_payment_str = notify_params.get("gmt_payment", "")
    if gmt_payment_str:
        try:
            payment_time = datetime.strptime(gmt_payment_str, "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() - payment_time > timedelta(hours=24):
                return PlainTextResponse("fail")
        except ValueError:
            pass

    if payload.trade_status not in {'TRADE_SUCCESS', 'TRADE_FINISHED'}:
        return {'ok': True, 'ignored': True}

    with tx() as conn:
        row = conn.execute(
            'SELECT order_no, user_id, plan, amount, status FROM orders WHERE order_no = ?',
            (payload.out_trade_no,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='order not found')

        if abs(Decimal(str(row['amount'])) - payload.total_amount) > Decimal('0.0001'):
            raise HTTPException(status_code=400, detail='amount mismatch')

        if row['status'] != 'paid':
            conn.execute(
                'UPDATE orders SET status = ?, paid_at = ? WHERE order_no = ?',
                ('paid', utc_now_iso(), payload.out_trade_no),
            )
            conn.execute(
                'INSERT OR REPLACE INTO subscriptions (user_id, plan, source, product_id, expires_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                (row['user_id'], row['plan'], 'alipay', None, None, utc_now_iso()),
            )

        return {'ok': True, 'order_no': payload.out_trade_no, 'plan_activated': row['plan'], 'status': 'paid'}


@app.post('/billing/revenuecat/webhook')
async def revenuecat_webhook(request: Request, authorization: str | None = Header(default=None)) -> dict:
    expected = f'Bearer {settings.revenuecat_webhook_secret}'
    if not settings.revenuecat_webhook_secret or authorization != expected:
        raise HTTPException(status_code=401, detail='invalid revenuecat webhook secret')

    body = await request.json()
    event = body.get('event') if isinstance(body, dict) else None
    if not isinstance(event, dict):
        raise HTTPException(status_code=422, detail='missing revenuecat event')

    user_id = event.get('app_user_id')
    product_id = event.get('product_id')
    event_type = str(event.get('type') or '').upper()
    entitlement_ids = event.get('entitlement_ids') or []
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=422, detail='missing revenuecat app_user_id')
    if entitlement_ids and settings.revenuecat_entitlement_id not in entitlement_ids:
        return {'ok': True, 'ignored': True}

    plan = _plan_from_revenuecat_product(product_id)
    if not plan:
        return {'ok': True, 'ignored': True}

    expires_at = None
    expiration_ms = event.get('expiration_at_ms')
    if isinstance(expiration_ms, int):
        expires_at = datetime.fromtimestamp(expiration_ms / 1000, UTC).isoformat()

    next_plan = 'free' if _revenuecat_event_is_inactive(event_type) else plan
    next_product_id = None if next_plan == 'free' else product_id

    with tx() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO subscriptions (user_id, plan, source, product_id, expires_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, next_plan, 'apple_iap', next_product_id, expires_at, utc_now_iso()),
        )
    return {'ok': True, 'user_id': user_id, 'plan': next_plan, 'source': 'apple_iap'}
