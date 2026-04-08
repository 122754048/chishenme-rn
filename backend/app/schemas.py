from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal

PlanName = Literal['free', 'pro', 'family']


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
    out_trade_no: str
    trade_status: str
    total_amount: float
    sign: str = Field(min_length=1)


class MembershipResponse(BaseModel):
    user_id: str
    plan: PlanName
    updated_at: datetime


class AuthRequest(BaseModel):
    user_id: str
    password: str = Field(min_length=6)


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal['bearer'] = 'bearer'
