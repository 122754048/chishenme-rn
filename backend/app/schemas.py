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


class NearbyRestaurantsRequest(BaseModel):
    kind: Literal['coordinates', 'query']
    latitude: float | None = None
    longitude: float | None = None
    radius_meters: int | None = Field(default=2400, alias='radiusMeters')
    query: str | None = None


class NearbyRestaurant(BaseModel):
    id: str
    name: str
    address: str
    rating: float | None = None
    review_count: int | None = Field(default=None, alias='reviewCount')
    distance_meters: int | None = Field(default=None, alias='distanceMeters')
    price_level: str | None = Field(default=None, alias='priceLevel')
    open_now: bool | None = Field(default=None, alias='openNow')
    primary_type: str | None = Field(default=None, alias='primaryType')
    image_url: str | None = Field(default=None, alias='imageUrl')
    editorial_summary: str | None = Field(default=None, alias='editorialSummary')


class NearbyRestaurantsResponse(BaseModel):
    restaurants: list[NearbyRestaurant]
    source: Literal['google_places', 'fallback']


class MenuScanItem(BaseModel):
    name: str
    description: str | None = None
    price: str | None = None
    recommendation: Literal['best', 'safe', 'avoid']
    reason: str
    caution: str | None = None


class MenuScanResponse(BaseModel):
    items: list[MenuScanItem]
    source: Literal['ai', 'fallback']
    note: str | None = None
