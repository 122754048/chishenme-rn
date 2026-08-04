# USFR MCP Foundation and Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reproducible new MCP project with an immutable imported USFR runtime, PostgreSQL persistence, local accounts, OAuth 2.1 PKCE, and an authenticated Streamable HTTP MCP endpoint.

**Architecture:** `usfr-mcp/` is the new persistent control plane. `usfr-runtime/` is generated from the supplied ZIP and addressed by a manifest digest; it is not edited by control-plane tasks. PostgreSQL owns durable identity/product state while OAuth access tokens authorize MCP requests.

**Tech Stack:** Python 3.12, FastAPI, MCP Python SDK, SQLAlchemy 2, Alembic, PostgreSQL 16, Authlib, argon2-cffi, pytest, Ruff, Docker Compose.

## Global Constraints

- Do not modify the local USFR Skill.
- Do not copy the ZIP's `.env` or secret values.
- Keep runtime import deterministic and hash-audited.
- Use authorization-code + PKCE with short-lived access tokens and hashed refresh tokens.
- No enterprise SSO, MFA, device binding, or IP allowlist in MVP.

---

### Task 1: Scaffold the control-plane package and deterministic runtime importer

**Files:**
- Create: `usfr-mcp/pyproject.toml`
- Create: `usfr-mcp/src/usfr_mcp/__init__.py`
- Create: `usfr-mcp/src/usfr_mcp/config.py`
- Create: `usfr-mcp/tools/import_runtime.py`
- Create: `usfr-mcp/tests/test_runtime_import.py`
- Create: `usfr-mcp/.gitignore`

**Interfaces:**
- Produces: `import_runtime(zip_path: Path, destination: Path, local_skill: Path) -> RuntimeImportResult`
- Produces: `RuntimeImportResult(source_zip_sha256: str, runtime_tree_sha256: str, local_skill_sha256: str, imported_files: tuple[str, ...])`

- [ ] **Step 1: Write the failing import-security test**

```python
def test_import_runtime_excludes_secrets_and_records_hashes(tmp_path, sample_zip):
    local_skill = tmp_path / "SKILL.md"
    local_skill.write_text("immutable test skill", encoding="utf-8")
    result = import_runtime(sample_zip, tmp_path / "runtime", local_skill)
    assert ".env" not in result.imported_files
    assert "server/public_fastapi_router.py" in result.imported_files
    assert len(result.source_zip_sha256) == 64
    assert len(result.runtime_tree_sha256) == 64
    assert len(result.local_skill_sha256) == 64
    assert not (tmp_path / "runtime" / ".env").exists()
```

- [ ] **Step 2: Run the test and verify the importer is missing**

Run: `cd usfr-mcp; python -m pytest tests/test_runtime_import.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing `import_runtime`.

- [ ] **Step 3: Implement canonical ZIP extraction**

Implement `import_runtime()` with `zipfile.ZipFile`, strip the archive's single top-level directory, reject absolute/parent-traversal paths, skip `.env`, caches, `.pyc`, generated reports, and write `runtime-origin.json` containing the ZIP digest, runtime-tree digest, read-only local Skill digest, and sorted imported paths. Compute the tree digest from `relative_path + NUL + file_sha256 + LF` records in lexicographic order. The CLI requires an explicit `--local-skill` path and never writes beneath it.

```python
def import_runtime(zip_path: Path, destination: Path, local_skill: Path) -> RuntimeImportResult:
    members = validated_members(ZipFile(zip_path))
    imported = extract_allowed_members(members, destination)
    result = build_import_result(zip_path, destination, local_skill, imported)
    write_json(destination / "runtime-origin.json", result.model_dump())
    return result
```

- [ ] **Step 4: Add project dependencies and secret ignores**

Declare Python `>=3.12`, `fastapi`, `uvicorn`, `mcp`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `authlib`, `argon2-cffi`, `httpx`, `pydantic-settings`, `redis`, `boto3`, `pytest`, and `ruff`. Ignore `.env*` except `.env.example`, `.venv`, caches, `usfr-runtime/`, local databases, and generated media.

```toml
[project]
requires-python = ">=3.12"
dependencies = ["fastapi==0.116.1", "mcp", "sqlalchemy>=2,<3", "alembic", "psycopg[binary]", "authlib", "argon2-cffi", "httpx", "pydantic-settings", "redis==5.2.1", "boto3"]
```

- [ ] **Step 5: Run focused tests and lint**

Run: `cd usfr-mcp; python -m pytest tests/test_runtime_import.py -v`
Expected: PASS.
Run: `cd usfr-mcp; python -m ruff check src tools tests`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```powershell
git add usfr-mcp/pyproject.toml usfr-mcp/.gitignore usfr-mcp/src/usfr_mcp usfr-mcp/tools/import_runtime.py usfr-mcp/tests/test_runtime_import.py
git commit -m "build(mcp): scaffold control plane and runtime importer"
```

### Task 2: Add typed configuration and startup secret validation

**Files:**
- Modify: `usfr-mcp/src/usfr_mcp/config.py`
- Create: `usfr-mcp/.env.example`
- Create: `usfr-mcp/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.load() -> Settings`
- Produces settings for PostgreSQL, Redis, OSS/MinIO, USFR API base URL, OAuth issuer/audience, signing key path, quota defaults, batch concurrency, and Provider readiness flags.

- [ ] **Step 1: Write failing validation tests**

```python
def test_production_rejects_short_secrets(monkeypatch):
    monkeypatch.setenv("USFR_MCP_ENV", "production")
    monkeypatch.setenv("USFR_MCP_JWT_SIGNING_SECRET", "short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings.load()

def test_defaults_match_approved_limits(valid_env):
    settings = Settings.load()
    assert settings.daily_output_limit == 50
    assert settings.monthly_budget_cny == Decimal("10000")
    assert settings.batch_max_items == 20
    assert settings.batch_default_concurrency == 5
```

- [ ] **Step 2: Run the tests**

Run: `cd usfr-mcp; python -m pytest tests/test_config.py -v`
Expected: FAIL because fields/validators do not exist.

- [ ] **Step 3: Implement settings**

Use `pydantic-settings`. Reject production secrets shorter than 32 UTF-8 bytes, public HTTP issuer URLs, batch maximums above 20, default concurrency outside 1–20, and non-positive budgets. Keep secret values as `SecretStr` and provide only a redacted `public_summary()`.

```python
class Settings(BaseSettings):
    daily_output_limit: int = 50
    monthly_budget_cny: Decimal = Decimal("10000")
    batch_max_items: int = 20
    batch_default_concurrency: int = 5

    @model_validator(mode="after")
    def validate_limits(self) -> "Settings":
        if not 1 <= self.batch_default_concurrency <= self.batch_max_items <= 20:
            raise ValueError("invalid batch limits")
        return self
```

- [ ] **Step 4: Write `.env.example` with empty secrets**

Include variable names and safe defaults only. Every credential field must be blank. Add comments that copied ZIP values must never be pasted automatically.

```dotenv
USFR_MCP_ENV=development
USFR_MCP_DATABASE_URL=postgresql+psycopg://usfr:usfr@postgres/usfr_mcp
USFR_MCP_REDIS_URL=redis://redis:6379/1
USFR_MCP_PUBLIC_URL=https://mcp.example.internal
USFR_MCP_USFR_API_URL=http://usfr-api:8080
USFR_MCP_JWT_SIGNING_SECRET=
USFR_MCP_CAPABILITY_ENCRYPTION_KEY=
OPENAI_API_KEY=
RUNNINGHUB_API_KEY=
RUNNINGHUB_SEEDANCE_API_KEY=
USFR_OSS_ACCESS_KEY_ID=
USFR_OSS_ACCESS_KEY_SECRET=
```

- [ ] **Step 5: Verify**

Run: `cd usfr-mcp; python -m pytest tests/test_config.py -v`
Expected: PASS.
Run: `cd usfr-mcp; python -m ruff check src tests`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add usfr-mcp/src/usfr_mcp/config.py usfr-mcp/.env.example usfr-mcp/tests/test_config.py
git commit -m "feat(mcp): validate runtime configuration and limits"
```

### Task 3: Create PostgreSQL models and initial migration

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/database.py`
- Create: `usfr-mcp/src/usfr_mcp/models/base.py`
- Create: `usfr-mcp/src/usfr_mcp/models/identity.py`
- Create: `usfr-mcp/src/usfr_mcp/models/replication.py`
- Create: `usfr-mcp/src/usfr_mcp/models/usage.py`
- Create: `usfr-mcp/alembic.ini`
- Create: `usfr-mcp/alembic/env.py`
- Create: `usfr-mcp/alembic/versions/0001_initial.py`
- Create: `usfr-mcp/tests/test_schema.py`

**Interfaces:**
- Produces: `session_scope() -> Iterator[Session]`
- Produces tables: `users`, `oauth_authorization_codes`, `oauth_refresh_tokens`, `settings`, `source_masters`, `analysis_caches`, `assets`, `replications`, `batches`, `batch_items`, `usage_reservations`, `usage_events`, `audit_events`.

- [ ] **Step 1: Write schema tests**

```python
def test_initial_schema_contains_required_tables(migrated_engine):
    names = set(inspect(migrated_engine).get_table_names())
    assert {
        "users", "oauth_authorization_codes", "oauth_refresh_tokens",
        "settings", "source_masters", "analysis_caches", "assets",
        "replications", "batches", "batch_items", "usage_reservations",
        "usage_events", "audit_events",
    } <= names
```

- [ ] **Step 2: Run migration test**

Run: `cd usfr-mcp; python -m pytest tests/test_schema.py -v`
Expected: FAIL because migration is absent.

- [ ] **Step 3: Implement models and constraints**

Use UUID primary keys, UTC timestamps, immutable SHA-256 columns as lowercase `CHAR(64)`, unique `(owner_user_id, source_sha256)` Source Master identity, unique analysis cache version tuple, unique `(batch_id, ordinal)`, and check constraints for ordinals `1..20`, concurrency `1..20`, and non-negative money values. Store only hashes of passwords, refresh tokens, and USFR capability tokens.

```python
class SourceMaster(Base):
    __tablename__ = "source_masters"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    source_sha256: Mapped[str] = mapped_column(CHAR(64))
    __table_args__ = (UniqueConstraint("owner_user_id", "source_sha256"),)
```

- [ ] **Step 4: Generate and inspect migration**

Run: `cd usfr-mcp; alembic upgrade head`
Expected: migration completes with all required tables and indexes.

- [ ] **Step 5: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_schema.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add usfr-mcp/src/usfr_mcp/database.py usfr-mcp/src/usfr_mcp/models usfr-mcp/alembic.ini usfr-mcp/alembic usfr-mcp/tests/test_schema.py
git commit -m "feat(mcp): add durable control-plane schema"
```

### Task 4: Implement local accounts and OAuth 2.1 PKCE

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/auth/passwords.py`
- Create: `usfr-mcp/src/usfr_mcp/auth/tokens.py`
- Create: `usfr-mcp/src/usfr_mcp/auth/oauth.py`
- Create: `usfr-mcp/src/usfr_mcp/auth/dependencies.py`
- Create: `usfr-mcp/tests/test_oauth.py`

**Interfaces:**
- Produces: `hash_password(password: str) -> str`
- Produces: `verify_password(hash_value: str, password: str) -> bool`
- Produces endpoints: `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, `/oauth/authorize`, `/oauth/token`.
- Produces: `require_principal(request) -> Principal(user_id: UUID, role: str)`

- [ ] **Step 1: Write PKCE and disabled-user tests**

```python
def test_token_exchange_requires_matching_pkce(client, user):
    code = authorize(client, user, code_challenge=s256("verifier"))
    response = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": "wrong",
    })
    assert response.status_code == 400

def test_disabled_user_cannot_call_protected_resource(request_factory, disabled_token):
    request = request_factory(headers={"Authorization": f"Bearer {disabled_token}"})
    with pytest.raises(AuthenticationRequired):
        require_principal(request)
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_oauth.py -v`
Expected: FAIL because OAuth routes are missing.

- [ ] **Step 3: Implement password and token storage**

Use Argon2id for passwords. Authorization codes expire after five minutes and are single-use. Access tokens expire after 15 minutes. Refresh tokens are opaque random 256-bit values, stored only as SHA-256 hashes, rotated on use, and revoked when the user is disabled.

```python
def hash_password(password: str) -> str:
    return PasswordHasher(type=Type.ID).hash(password)

def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Implement OAuth metadata and PKCE flow**

Require `S256`, exact redirect URI matching, issuer/audience validation, and scopes `usfr:read`, `usfr:write`, `usfr:admin`. Return RFC 9728 protected-resource metadata and OAuth server discovery metadata. Never accept passwords through MCP tool arguments.

```python
@router.post("/oauth/token")
def exchange_token(form: TokenForm, session: Session = Depends(db_session)) -> TokenResponse:
    grant = consume_authorization_code(session, form.code)
    verify_s256(grant.code_challenge, form.code_verifier)
    return issue_rotating_tokens(session, grant.user_id, grant.scopes)
```

- [ ] **Step 5: Run security tests**

Run: `cd usfr-mcp; python -m pytest tests/test_oauth.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add usfr-mcp/src/usfr_mcp/auth usfr-mcp/tests/test_oauth.py
git commit -m "feat(mcp): add local OAuth PKCE authentication"
```

### Task 5: Expose authenticated Streamable HTTP MCP and readiness

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/mcp_server.py`
- Create: `usfr-mcp/src/usfr_mcp/app.py`
- Create: `usfr-mcp/src/usfr_mcp/readiness.py`
- Create: `usfr-mcp/tests/test_mcp_server.py`

**Interfaces:**
- Produces endpoint: `/mcp`
- Produces tools: `whoami`, `get_service_limits`
- Produces endpoints: `/healthz`, `/readyz`

- [ ] **Step 1: Write authentication and metadata tests**

```python
def test_mcp_rejects_missing_bearer(mcp_client):
    response = mcp_client.initialize(headers={})
    assert response.status_code == 401

def test_whoami_returns_only_public_identity(authenticated_mcp):
    result = authenticated_mcp.call_tool("whoami", {})
    assert UUID(result.structured_content["user_id"])
    assert result.structured_content["role"] == "user"
    assert "token" not in json.dumps(result.structured_content).lower()
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_mcp_server.py -v`
Expected: FAIL because MCP app is missing.

- [ ] **Step 3: Implement the MCP server**

Create a stable server named `usfr-replication` with instructions stating that preview must precede confirmation and ambiguous batch inputs must not be guessed. Mark `whoami` and `get_service_limits` as read-only. Put only user-safe fields in `structuredContent`; keep internal IDs in `_meta` only when they are not credentials.

```python
mcp = FastMCP("usfr-replication", instructions=SERVER_INSTRUCTIONS)

@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def whoami(ctx: Context) -> dict[str, str]:
    principal = principal_from_context(ctx)
    return {"user_id": str(principal.user_id), "role": principal.role}
```

- [ ] **Step 4: Implement readiness**

`/healthz` reports process liveness. `/readyz` verifies PostgreSQL migration head, Redis connectivity, runtime-origin digest presence, and copied USFR `/readyz`; it must not print connection strings or credentials.

```python
def readiness_report(checks: ReadinessChecks) -> dict[str, object]:
    results = checks.run_all()
    return {"ready": all(item.passed for item in results.values()), "checks": sanitize(results)}
```

- [ ] **Step 5: Run tests and MCP Inspector smoke test**

Run: `cd usfr-mcp; python -m pytest tests/test_mcp_server.py -v`
Expected: PASS.
Run: `npx @modelcontextprotocol/inspector` and connect to `http://localhost:8081/mcp`.
Expected: initialization succeeds after OAuth, and both tools have correct read-only annotations.

- [ ] **Step 6: Commit**

```powershell
git add usfr-mcp/src/usfr_mcp/mcp_server.py usfr-mcp/src/usfr_mcp/app.py usfr-mcp/src/usfr_mcp/readiness.py usfr-mcp/tests/test_mcp_server.py
git commit -m "feat(mcp): expose authenticated streamable HTTP server"
```

### Task 6: Foundation regression gate

**Files:**
- Create: `usfr-mcp/scripts/verify_foundation.py`
- Create: `usfr-mcp/tests/test_foundation_gate.py`

**Interfaces:**
- Produces command: `python scripts/verify_foundation.py`

- [ ] **Step 1: Write a failing gate test**

The test must assert that the verifier checks runtime import digest, local Skill digest read-only status, migration head, OAuth metadata, and MCP initialization.

```python
def test_foundation_gate_requires_every_check(verifier):
    report = verifier.run()
    assert set(report.checks) == {
        "runtime_import_digest",
        "local_skill_digest",
        "migration_head",
        "oauth_metadata",
        "mcp_initialization",
    }
    assert report.passed == all(check.passed for check in report.checks.values())
```

- [ ] **Step 2: Implement the verifier**

Return non-zero on any failure and emit a JSON summary containing only booleans, versions, and SHA-256 values.

```python
def main() -> int:
    report = FoundationVerifier.from_environment().run()
    print(json.dumps(report.public_dict(), sort_keys=True))
    return 0 if report.passed else 1
```

- [ ] **Step 3: Run complete foundation suite**

Run: `cd usfr-mcp; python -m pytest -q`
Expected: all foundation tests pass.
Run: `cd usfr-mcp; python scripts/verify_foundation.py`
Expected: exit 0 with `"passed": true`.

- [ ] **Step 4: Commit**

```powershell
git add usfr-mcp/scripts/verify_foundation.py usfr-mcp/tests/test_foundation_gate.py
git commit -m "test(mcp): add foundation verification gate"
```
