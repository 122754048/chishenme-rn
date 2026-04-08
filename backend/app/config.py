import os
from dataclasses import dataclass


@dataclass
class Settings:
    app_name: str = os.getenv('APP_NAME', 'chishenme-backend')
    env: str = os.getenv('APP_ENV', 'dev')
    jwt_secret: str = os.getenv('JWT_SECRET', 'replace-in-prod')
    jwt_algo: str = os.getenv('JWT_ALGO', 'HS256')
    jwt_exp_minutes: int = int(os.getenv('JWT_EXP_MINUTES', str(60 * 24 * 30)))
    db_path: str = os.getenv('DB_PATH', 'backend/app/chishenme.db')
    free_daily_quota: int = int(os.getenv('FREE_DAILY_QUOTA', '3'))
    alipay_app_id: str = os.getenv('ALIPAY_APP_ID', 'your-alipay-app-id')
    alipay_public_key: str = os.getenv('ALIPAY_PUBLIC_KEY', 'replace-with-alipay-public-key')
    alipay_notify_token: str = os.getenv('ALIPAY_NOTIFY_TOKEN', 'replace-with-server-side-notify-token')

    def assert_runtime_safe(self) -> None:
        if self.env.lower() not in {'prod', 'production'}:
            return
        unsafe_pairs = {
            'JWT_SECRET': self.jwt_secret,
            'ALIPAY_NOTIFY_TOKEN': self.alipay_notify_token,
            'ALIPAY_PUBLIC_KEY': self.alipay_public_key,
        }
        placeholders = {
            'replace-in-prod',
            'replace-with-server-side-notify-token',
            'replace-with-alipay-public-key',
        }
        missing = [name for name, value in unsafe_pairs.items() if (not value) or (value in placeholders)]
        if missing:
            raise ValueError(f'unsafe production settings: {", ".join(missing)}')


settings = Settings()
