from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .replication_runtime import mount_commercial_batch_api
from .replication_v2 import load_runtime_dependencies, mount_replication_v2


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.assert_runtime_safe()
    yield


app = FastAPI(title="USFR Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

runtime_dependencies = load_runtime_dependencies()
mount_replication_v2(app, runtime_dependencies=runtime_dependencies)
mount_commercial_batch_api(app, runtime=runtime_dependencies.get("commercial_batch_runtime"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "usfr"}
