import unittest

from app.config import Settings


class SettingsTest(unittest.TestCase):
    def test_prod_requires_non_placeholder_secrets(self):
        settings = Settings(
            env='production',
            jwt_secret='replace-in-prod',
            alipay_notify_token='replace-with-server-side-notify-token',
            alipay_public_key='replace-with-alipay-public-key',
        )
        with self.assertRaises(ValueError):
            settings.assert_runtime_safe()

    def test_non_prod_allows_placeholder_secrets(self):
        settings = Settings(
            env='dev',
            jwt_secret='replace-in-prod',
            alipay_notify_token='replace-with-server-side-notify-token',
            alipay_public_key='replace-with-alipay-public-key',
        )
        settings.assert_runtime_safe()


if __name__ == '__main__':
    unittest.main()
