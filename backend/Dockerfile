# ─────────────────────────────────────────────
# Stage 1: builder — install deps into a venv
# ─────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools (needed for psycopg2-binary and other C-extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create isolated venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python deps (requirements.txt already includes psycopg2-binary)
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────
# Stage 2: runtime — lean final image
# ─────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Runtime system deps: libpq5 for psycopg2, curl for HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (uid/gid 1001)
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home --shell /sbin/nologin appuser

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# App directory owned by non-root user
# backend/ contents are copied directly (COPY . . from backend/ build context)
WORKDIR /app
COPY --chown=appuser:appgroup . .

# Data volume for SQLite fallback (only used when DATABASE_URL is not set / not postgres://)
RUN mkdir -p /data && chown appuser:appgroup /data

USER appuser

# Expose port
EXPOSE 8000

# Health check — calls the /health endpoint defined in app/main.py
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production entrypoint
# app.main:app matches the module path backend/app/main.py → app = FastAPI(...)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--no-access-log"]
