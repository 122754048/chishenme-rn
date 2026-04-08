import os
import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


class BackendApiTest(unittest.TestCase):
    def setUp(self):
        if os.path.exists(settings.db_path):
            os.remove(settings.db_path)
        self.client = TestClient(app)
        self.client.get('/health')

        reg = self.client.post('/auth/register', json={'user_id': 'u_123', 'password': 'secret123'})
        self.assertEqual(reg.status_code, 200)
        self.token = reg.json()['access_token']
        self.headers = {'Authorization': f'Bearer {self.token}'}

    def test_plan_and_quota_flow(self):
        plans = self.client.get('/plans')
        self.assertEqual(plans.status_code, 200)
        self.assertEqual(len(plans.json()), 3)

        quota = self.client.get('/quota/today', headers=self.headers)
        self.assertEqual(quota.status_code, 200)
        self.assertEqual(quota.json()['left'], 3)

        for expected_left in [2, 1, 0]:
            consume = self.client.post('/quota/consume', headers=self.headers, json={})
            self.assertEqual(consume.status_code, 200)
            self.assertTrue(consume.json()['allowed'])
            self.assertEqual(consume.json()['left'], expected_left)

        blocked = self.client.post('/quota/consume', headers=self.headers, json={})
        self.assertEqual(blocked.status_code, 200)
        self.assertFalse(blocked.json()['allowed'])
        self.assertEqual(blocked.json()['left'], 0)

    def test_alipay_order_notify(self):
        created = self.client.post(
            '/billing/alipay/create-order',
            headers=self.headers,
            json={'plan': 'pro'},
        )
        self.assertEqual(created.status_code, 200)
        order_no = created.json()['order_no']

        order_before = self.client.get(f'/billing/orders/{order_no}', headers=self.headers)
        self.assertEqual(order_before.status_code, 200)
        self.assertEqual(order_before.json()['status'], 'created')

        bad_sign = self.client.post('/billing/alipay/notify', json={
            'out_trade_no': order_no,
            'trade_status': 'TRADE_SUCCESS',
            'total_amount': 9.9,
            'sign': 'bad-sign',
        })
        self.assertEqual(bad_sign.status_code, 401)

        ok_notify = self.client.post('/billing/alipay/notify', json={
            'out_trade_no': order_no,
            'trade_status': 'TRADE_SUCCESS',
            'total_amount': 9.9,
            'sign': settings.alipay_notify_token,
        })
        self.assertEqual(ok_notify.status_code, 200)

        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.status_code, 200)
        self.assertEqual(membership.json()['plan'], 'pro')

    def test_create_order_idempotency(self):
        created = self.client.post(
            '/billing/alipay/create-order',
            headers=self.headers,
            json={'plan': 'family'},
        )
        self.assertEqual(created.status_code, 200)
        first_order_no = created.json()['order_no']

        idem_headers = {**self.headers, 'Idempotency-Key': 'idem-order-1'}
        first_idem = self.client.post('/billing/alipay/create-order', headers=idem_headers, json={'plan': 'family'})
        second_idem = self.client.post('/billing/alipay/create-order', headers=idem_headers, json={'plan': 'family'})
        self.assertEqual(first_idem.status_code, 200)
        self.assertEqual(second_idem.status_code, 200)
        self.assertEqual(first_idem.json()['order_no'], second_idem.json()['order_no'])

        self.assertNotEqual(first_order_no, first_idem.json()['order_no'])


if __name__ == '__main__':
    unittest.main()
