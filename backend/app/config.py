import os
from dataclasses import dataclass


@dataclass
class Settings:
    """Configuration owned by the USFR service shell.

    Provider, Redis, object-store, and capability settings are read by the
    deployment-owned USFR runtime factory.  They intentionally do not become
    generic backend settings or browser-visible configuration.
    """

    app_name: str = os.getenv("APP_NAME", "usfr-backend")
    env: str = os.getenv("APP_ENV", "dev")

    def assert_runtime_safe(self) -> None:
        """Keep the FastAPI lifecycle hook while USFR validates its own runtime."""


settings = Settings()
