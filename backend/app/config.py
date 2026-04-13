import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_db_path() -> str:
    return str(PROJECT_ROOT / 'backend' / 'app' / 'chishenme.db')


@dataclass
class Settings:
    app_name: str = os.getenv('APP_NAME', 'chishenme-backend')
    env: str = os.getenv('APP_ENV', 'dev')
    jwt_secret: str = os.getenv('JWT_SECRET', 'replace-in-prod')
    jwt_algo: str = os.getenv('JWT_ALGO', 'HS256')
    jwt_exp_minutes: int = int(os.getenv('JWT_EXP_MINUTES', str(60 * 24 * 30)))
    db_path: str = os.getenv('DB_PATH', _default_db_path())
    free_daily_quota: int = int(os.getenv('FREE_DAILY_QUOTA', '3'))
    alipay_app_id: str = os.getenv('ALIPAY_APP_ID', 'your-alipay-app-id')
    alipay_public_key: str = os.getenv('ALIPAY_PUBLIC_KEY', 'replace-with-alipay-public-key')
    revenuecat_webhook_secret: str = os.getenv('REVENUECAT_WEBHOOK_SECRET', '')
    revenuecat_entitlement_id: str = os.getenv('REVENUECAT_ENTITLEMENT_ID', 'premium')
    revenuecat_pro_product_id: str = os.getenv('REVENUECAT_PRO_PRODUCT_ID', 'teller.pro.monthly')
    revenuecat_family_product_id: str = os.getenv('REVENUECAT_FAMILY_PRODUCT_ID', 'teller.family.monthly')
    google_places_api_key: str = os.getenv('GOOGLE_PLACES_API_KEY', '')
    openai_api_key: str = os.getenv('OPENAI_API_KEY', '')

    def assert_runtime_safe(self) -> None:
        if self.env.lower() not in {'prod', 'production'}:
            return
        unsafe_pairs = {
            'JWT_SECRET': self.jwt_secret,
            'ALIPAY_APP_ID': self.alipay_app_id,
            'ALIPAY_PUBLIC_KEY': self.alipay_public_key,
            'REVENUECAT_WEBHOOK_SECRET': self.revenuecat_webhook_secret,
            'REVENUECAT_PRO_PRODUCT_ID': self.revenuecat_pro_product_id,
            'REVENUECAT_FAMILY_PRODUCT_ID': self.revenuecat_family_product_id,
            'GOOGLE_PLACES_API_KEY': self.google_places_api_key,
            'OPENAI_API_KEY': self.openai_api_key,
        }
        placeholders = {
            'your-alipay-app-id',
            'replace-in-prod',
            'replace-with-alipay-public-key',
            'teller.pro.monthly',
            'teller.family.monthly',
        }
        missing = [name for name, value in unsafe_pairs.items() if (not value) or (value in placeholders)]
        if missing:
            raise ValueError(f'unsafe production settings: {", ".join(missing)}')


settings = Settings()
