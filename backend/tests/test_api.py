import os
import base64
import tempfile
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.main import app
from app.config import settings
from app.db import init_db
from app.services.alipay import build_alipay_sign_content


class BackendApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alipay_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = cls.alipay_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        settings.alipay_public_key = public_key.decode('utf-8')
        settings.alipay_app_id = 'test-alipay-app-id'
        settings.revenuecat_webhook_secret = 'test-revenuecat-secret'
        settings.revenuecat_entitlement_id = 'premium'
        settings.revenuecat_pro_product_id = 'chishenme.pro.monthly'
        settings.revenuecat_family_product_id = 'chishenme.family.monthly'
        settings.google_places_api_key = ''
        settings.openai_api_key = ''

    def setUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), f'chishenme-test-{uuid4().hex}.db')
        settings.db_path = self.db_path
        init_db()
        self.client = TestClient(app)

        reg = self.client.post('/auth/register', json={'user_id': 'u_123', 'password': 'secret123'})
        self.assertEqual(reg.status_code, 200)
        self.token = reg.json()['access_token']
        self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        self.client.close()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def signed_alipay_payload(self, **overrides):
        payload = {
            'app_id': settings.alipay_app_id,
            'out_trade_no': overrides.pop('out_trade_no'),
            'trade_status': overrides.pop('trade_status', 'TRADE_SUCCESS'),
            'total_amount': overrides.pop('total_amount', 9.9),
            'sign_type': overrides.pop('sign_type', 'RSA2'),
            **overrides,
        }
        signature = self.alipay_private_key.sign(
            build_alipay_sign_content(payload).encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        payload['sign'] = base64.b64encode(signature).decode('ascii')
        return payload

    def create_order(self, plan='pro'):
        created = self.client.post(
            '/billing/alipay/create-order',
            headers=self.headers,
            json={'plan': plan},
        )
        self.assertEqual(created.status_code, 200)
        return created.json()['order_no']

    def revenuecat_event(self, user_id='u_123', product_id='chishenme.pro.monthly', event_type='INITIAL_PURCHASE'):
        return {
            'event': {
                'app_user_id': user_id,
                'type': event_type,
                'product_id': product_id,
                'entitlement_ids': [settings.revenuecat_entitlement_id],
                'expiration_at_ms': 1893456000000,
            },
        }

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
        order_no = self.create_order('pro')

        order_before = self.client.get(f'/billing/orders/{order_no}', headers=self.headers)
        self.assertEqual(order_before.status_code, 200)
        self.assertEqual(order_before.json()['status'], 'created')

        bad_sign = self.client.post('/billing/alipay/notify', json={
            'app_id': settings.alipay_app_id,
            'out_trade_no': order_no,
            'trade_status': 'TRADE_SUCCESS',
            'total_amount': 9.9,
            'sign_type': 'RSA2',
            'sign': 'bad-sign',
        })
        self.assertEqual(bad_sign.status_code, 401)

        ok_notify = self.client.post(
            '/billing/alipay/notify',
            data=self.signed_alipay_payload(out_trade_no=order_no, total_amount='9.90'),
        )
        self.assertEqual(ok_notify.status_code, 200)

        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.status_code, 200)
        self.assertEqual(membership.json()['plan'], 'pro')

    def test_alipay_notify_rejects_wrong_app_id(self):
        order_no = self.create_order('pro')
        payload = self.signed_alipay_payload(out_trade_no=order_no, app_id='attacker-app-id')

        response = self.client.post('/billing/alipay/notify', data=payload)

        self.assertEqual(response.status_code, 401)
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.json()['plan'], 'free')

    def test_alipay_notify_rejects_amount_mismatch(self):
        order_no = self.create_order('pro')
        payload = self.signed_alipay_payload(out_trade_no=order_no, total_amount='1.00')

        response = self.client.post('/billing/alipay/notify', data=payload)

        self.assertEqual(response.status_code, 400)
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.json()['plan'], 'free')

    def test_alipay_notify_ignores_unpaid_trade_status(self):
        order_no = self.create_order('pro')
        payload = self.signed_alipay_payload(out_trade_no=order_no, trade_status='WAIT_BUYER_PAY')

        response = self.client.post('/billing/alipay/notify', data=payload)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.json()['plan'], 'free')
        order = self.client.get(f'/billing/orders/{order_no}', headers=self.headers)
        self.assertEqual(order.json()['status'], 'created')

    def test_order_status_is_user_scoped(self):
        order_no = self.create_order('family')
        reg = self.client.post('/auth/register', json={'user_id': 'u_456', 'password': 'secret456'})
        self.assertEqual(reg.status_code, 200)
        other_headers = {'Authorization': f"Bearer {reg.json()['access_token']}"}

        response = self.client.get(f'/billing/orders/{order_no}', headers=other_headers)

        self.assertEqual(response.status_code, 404)

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

    def test_revenuecat_webhook_activates_pro_plan(self):
        response = self.client.post(
            '/billing/revenuecat/webhook',
            headers={'Authorization': f'Bearer {settings.revenuecat_webhook_secret}'},
            json=self.revenuecat_event(product_id=settings.revenuecat_pro_product_id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['plan'], 'pro')
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.json()['plan'], 'pro')
        self.assertEqual(membership.json()['source'], 'apple_iap')
        self.assertEqual(membership.json()['product_id'], settings.revenuecat_pro_product_id)

    def test_revenuecat_webhook_activates_family_plan(self):
        response = self.client.post(
            '/billing/revenuecat/webhook',
            headers={'Authorization': f'Bearer {settings.revenuecat_webhook_secret}'},
            json=self.revenuecat_event(product_id=settings.revenuecat_family_product_id),
        )

        self.assertEqual(response.status_code, 200)
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.json()['plan'], 'family')
        self.assertEqual(membership.json()['source'], 'apple_iap')

    def test_revenuecat_webhook_expiration_returns_to_free(self):
        active = self.client.post(
            '/billing/revenuecat/webhook',
            headers={'Authorization': f'Bearer {settings.revenuecat_webhook_secret}'},
            json=self.revenuecat_event(product_id=settings.revenuecat_pro_product_id),
        )
        self.assertEqual(active.status_code, 200)

        expired = self.client.post(
            '/billing/revenuecat/webhook',
            headers={'Authorization': f'Bearer {settings.revenuecat_webhook_secret}'},
            json=self.revenuecat_event(product_id=settings.revenuecat_pro_product_id, event_type='EXPIRATION'),
        )

        self.assertEqual(expired.status_code, 200)
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.json()['plan'], 'free')
        self.assertEqual(membership.json()['source'], 'apple_iap')
        self.assertIsNone(membership.json()['product_id'])

    def test_revenuecat_webhook_rejects_invalid_secret(self):
        response = self.client.post(
            '/billing/revenuecat/webhook',
            headers={'Authorization': 'Bearer wrong-secret'},
            json=self.revenuecat_event(product_id=settings.revenuecat_pro_product_id),
        )

        self.assertEqual(response.status_code, 401)
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.json()['plan'], 'free')

    def test_register_preserves_existing_revenuecat_subscription(self):
        user_id = 'pre_registered_iap_user'
        webhook = self.client.post(
            '/billing/revenuecat/webhook',
            headers={'Authorization': f'Bearer {settings.revenuecat_webhook_secret}'},
            json=self.revenuecat_event(user_id=user_id, product_id=settings.revenuecat_pro_product_id),
        )
        self.assertEqual(webhook.status_code, 200)

        registered = self.client.post('/auth/register', json={'user_id': user_id, 'password': 'secret789'})
        self.assertEqual(registered.status_code, 200)
        headers = {'Authorization': f"Bearer {registered.json()['access_token']}"}
        membership = self.client.get('/membership/me', headers=headers)

        self.assertEqual(membership.status_code, 200)
        self.assertEqual(membership.json()['plan'], 'pro')
        self.assertEqual(membership.json()['source'], 'apple_iap')

    def test_account_delete_removes_user_data(self):
        self.create_order('pro')
        self.client.post('/quota/consume', headers=self.headers, json={})
        delete_response = self.client.delete('/account/me', headers=self.headers)

        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.json()['deleted'])
        login = self.client.post('/auth/login', json={'user_id': 'u_123', 'password': 'secret123'})
        self.assertEqual(login.status_code, 401)
        membership = self.client.get('/membership/me', headers=self.headers)
        self.assertEqual(membership.status_code, 401)

    def test_nearby_restaurants_fallback_without_google_key(self):
        response = self.client.post(
            '/discovery/nearby-restaurants',
            headers=self.headers,
            json={'kind': 'query', 'query': 'SoHo, New York'},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['source'], 'fallback')
        self.assertGreaterEqual(len(body['restaurants']), 1)
        self.assertIn('name', body['restaurants'][0])

    def test_menu_scan_fallback_without_openai_key(self):
        response = self.client.post(
            '/discovery/menu-scan',
            headers=self.headers,
            files={'file': ('menu.jpg', b'fake-image-bytes', 'image/jpeg')},
            data={
                'cuisines': '["JapaneseKorean"]',
                'restrictions': '["dairy"]',
                'restaurant_name': 'Paper Lantern',
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['source'], 'fallback')
        self.assertGreaterEqual(len(body['items']), 1)
        self.assertIn(body['items'][0]['recommendation'], {'best', 'safe', 'avoid'})


if __name__ == '__main__':
    unittest.main()
