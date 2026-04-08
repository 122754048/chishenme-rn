import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Depends

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
)
from .security import hash_password, verify_password, create_access_token, decode_access_token

app = FastAPI(title=settings.app_name)


@app.on_event('startup')
def on_startup() -> None:
    settings.assert_runtime_safe()
    init_db()


def _today() -> str:
    return datetime.utcnow().date().isoformat()


def _current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail='missing bearer token')
    token = authorization.split(' ', 1)[1].strip()
    try:
        return decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _plan_for_user(conn, user_id: str) -> str:
    row = conn.execute('SELECT plan FROM subscriptions WHERE user_id = ?', (user_id,)).fetchone()
    return row['plan'] if row else 'free'


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
def register(payload: AuthRequest) -> AuthResponse:
    with tx() as conn:
        existed = conn.execute('SELECT 1 FROM users WHERE user_id = ?', (payload.user_id,)).fetchone()
        if existed:
            raise HTTPException(status_code=409, detail='user already exists')

        conn.execute(
            'INSERT INTO users (user_id, password_hash, created_at) VALUES (?, ?, ?)',
            (payload.user_id, hash_password(payload.password), utc_now_iso()),
        )
        conn.execute(
            'INSERT INTO subscriptions (user_id, plan, updated_at) VALUES (?, ?, ?)',
            (payload.user_id, 'free', utc_now_iso()),
        )

    return AuthResponse(access_token=create_access_token(payload.user_id))


@app.post('/auth/login', response_model=AuthResponse)
def login(payload: AuthRequest) -> AuthResponse:
    with tx() as conn:
        row = conn.execute('SELECT password_hash FROM users WHERE user_id = ?', (payload.user_id,)).fetchone()
        if not row or not verify_password(payload.password, row['password_hash']):
            raise HTTPException(status_code=401, detail='invalid credentials')
    return AuthResponse(access_token=create_access_token(payload.user_id))


@app.get('/plans', response_model=list[Plan])
def plans() -> list[Plan]:
    return [
        Plan(key='free', title='免费版', monthly_price_cny=0),
        Plan(key='pro', title='Pro', monthly_price_cny=9.9),
        Plan(key='family', title='家庭版', monthly_price_cny=19.9),
    ]


@app.get('/membership/me', response_model=MembershipResponse)
def membership_me(user_id: str = Depends(_current_user)) -> MembershipResponse:
    with tx() as conn:
        plan = _plan_for_user(conn, user_id)
    return MembershipResponse(user_id=user_id, plan=plan, updated_at=datetime.utcnow())


@app.get('/quota/today', response_model=QuotaResponse)
def quota_today(user_id: str = Depends(_current_user)) -> QuotaResponse:
    with tx() as conn:
        q = _quota_for_user(conn, user_id)
    return QuotaResponse(**q)


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
        order_no = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
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


@app.post('/billing/alipay/notify')
def alipay_notify(payload: AlipayNotifyPayload) -> dict:
    # TODO: replace with RSA2 verification using Alipay official signature process
    if payload.sign != settings.alipay_notify_token:
        raise HTTPException(status_code=401, detail='invalid notify signature')

    if payload.trade_status not in {'TRADE_SUCCESS', 'TRADE_FINISHED'}:
        return {'ok': True, 'ignored': True}

    with tx() as conn:
        row = conn.execute(
            'SELECT order_no, user_id, plan, amount, status FROM orders WHERE order_no = ?',
            (payload.out_trade_no,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='order not found')

        if abs(float(row['amount']) - payload.total_amount) > 0.0001:
            raise HTTPException(status_code=400, detail='amount mismatch')

        if row['status'] != 'paid':
            conn.execute(
                'UPDATE orders SET status = ?, paid_at = ? WHERE order_no = ?',
                ('paid', utc_now_iso(), payload.out_trade_no),
            )
            conn.execute(
                'INSERT OR REPLACE INTO subscriptions (user_id, plan, updated_at) VALUES (?, ?, ?)',
                (row['user_id'], row['plan'], utc_now_iso()),
            )

        return {'ok': True, 'order_no': payload.out_trade_no, 'plan_activated': row['plan'], 'status': 'paid'}
