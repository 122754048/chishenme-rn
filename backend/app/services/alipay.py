from datetime import datetime
from uuid import uuid4
from typing import Dict


class AlipayService:
    """Skeleton Alipay service.

    NOTE: This service is intentionally stubbed. In production:
    1) Build signed request payload with RSA2.
    2) Verify async callback signature.
    3) Validate app_id, seller_id, total_amount, order_no.
    """

    def __init__(self):
        self.orders: Dict[str, dict] = {}

    def create_order(self, user_id: str, plan: str) -> dict:
        if plan not in {'pro', 'family'}:
            raise ValueError('unsupported plan')
        order_no = datetime.utcnow().strftime('%Y%m%d%H%M%S') + uuid4().hex[:10]
        amount = 9.9 if plan == 'pro' else 19.9
        order = {
            'order_no': order_no,
            'user_id': user_id,
            'plan': plan,
            'amount': amount,
            'status': 'created',
            'created_at': datetime.utcnow(),
        }
        self.orders[order_no] = order
        return {
            'order_no': order_no,
            'status': 'created',
            'pay_url': f'https://openapi.alipay.com/gateway.do?out_trade_no={order_no}',
        }

    def get_order(self, order_no: str) -> dict | None:
        return self.orders.get(order_no)

    def mark_paid(self, order_no: str) -> dict | None:
        order = self.orders.get(order_no)
        if not order:
            return None
        if order['status'] == 'paid':
            return order
        order['status'] = 'paid'
        order['paid_at'] = datetime.utcnow()
        return order
