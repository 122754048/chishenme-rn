from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

PlanName = Literal['free', 'pro', 'family']
SubscriptionSource = Literal['local', 'alipay', 'apple_iap']


class Plan(BaseModel):
    key: PlanName
    title: str
    monthly_price_cny: float


class QuotaResponse(BaseModel):
    date: str
    left: int


class QuotaConsumeRequest(BaseModel):
    pass


class QuotaConsumeResponse(BaseModel):
    allowed: bool
    date: str
    left: int


class OrderCreateRequest(BaseModel):
    plan: Literal['pro', 'family']


class OrderCreateResponse(BaseModel):
    order_no: str
    status: Literal['created']
    pay_url: str


class OrderStatusResponse(BaseModel):
    order_no: str
    user_id: str
    plan: Literal['pro', 'family']
    amount: float
    status: Literal['created', 'paid', 'failed']


class AlipayNotifyPayload(BaseModel):
    model_config = ConfigDict(extra='allow')

    app_id: str
    out_trade_no: str
    trade_status: str
    total_amount: Decimal
    sign_type: Literal['RSA2'] = 'RSA2'
    sign: str = Field(min_length=1)


class MembershipResponse(BaseModel):
    user_id: str
    plan: PlanName
    updated_at: datetime
    source: SubscriptionSource = 'local'
    product_id: str | None = None
    expires_at: str | None = None


class AccountDeletionResponse(BaseModel):
    deleted: bool


class AuthRequest(BaseModel):
    user_id: str
    password: str = Field(min_length=6)


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal['bearer'] = 'bearer'
