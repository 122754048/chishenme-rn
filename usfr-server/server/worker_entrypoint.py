"""Container entrypoint for the Worker or cleanup Sweeper process role."""

from __future__ import annotations

import importlib
import os
from typing import Any


PROCESS_ROLE_ENV = "USFR_PROCESS_ROLE"
_BOOTSTRAP_ENVIRONMENTS = {
    "worker": "USFR_WORKER_BOOTSTRAP",
    "sweeper": "USFR_SWEEPER_BOOTSTRAP",
}


def _load(spec: str) -> Any:
    module_name, separator, function_name = spec.partition(":")
    if not separator or not module_name or not function_name:
        raise SystemExit("USFR_WORKER_BOOTSTRAP must be module:function")
    module = importlib.import_module(module_name)
    callback = getattr(module, function_name, None)
    if not callable(callback):
        raise SystemExit(f"worker bootstrap is not callable: {spec}")
    return callback


def main() -> int:
    role = (os.getenv(PROCESS_ROLE_ENV, "worker") or "worker").strip().casefold()
    environment_name = _BOOTSTRAP_ENVIRONMENTS.get(role)
    if environment_name is None:
        raise SystemExit(f"{PROCESS_ROLE_ENV} must be worker or sweeper")
    spec = os.getenv(environment_name, "").strip()
    if not spec:
        raise SystemExit(
            f"{environment_name} is required; inject the packaged {role} bootstrap"
        )
    result = _load(spec)()
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
