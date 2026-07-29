from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from .errors import (
    ApprovalStaleError,
    IdempotencyConflictError,
    JobGoneError,
    ReplicationError,
    RevisionConflictError,
    StateConflictError,
)
from .job_models import ArtifactRef, JobSnapshot, ProviderAttempt, StageCheckpoint
from .job_store import EphemeralJobStore
from .recovery_models import RecoveryCheckpoint
from .review_models import RevisionManifest, RevisionRequest, StoryboardCutRef


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ACTIVE_PROVIDER_STATUSES = ("SUBMITTING", "RUNNING", "AMBIGUOUS")
_PROVIDER_STATUSES = ("PREPARED", "SUBMITTING", "RUNNING", "AMBIGUOUS", "SUCCEEDED", "FAILED")
_PROVIDER_OPERATIONS = ("CreateAsset", "CreateVideo")
_SNAPSHOT_MUTABLE_FIELDS = {
    "state",
    "slots_manifest",
    "review_route",
    "current_script_revision",
    "approved_script_sha256",
    "current_storyboard_revision",
    "approved_storyboard_sha256",
    "final_ref",
}


class _StageAttemptStale(Exception):
    """Internal signal for one request-local stage-claim retry."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ReplicationError("INVALID_INPUT", "value is not JSON serializable", details={"type": type(value).__name__}) from exc


def _json_load(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _require_ttl(value: int, *, field: str = "ttl_seconds") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReplicationError("INVALID_INPUT", f"{field} must be a positive integer")
    return value


def _require_retention_ms(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReplicationError("INVALID_INPUT", "provider_retention_ms must be a positive finite integer")
    return value


def _require_sha(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReplicationError("INVALID_INPUT", f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_nonempty_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReplicationError("INVALID_INPUT", f"{field} must be a non-empty string")
    return value


def _require_key_component(value: Any, *, field: str, allow_colon: bool = True) -> str:
    text = _require_nonempty_text(value, field=field)
    forbidden = set("*?[]{}\x00\r\n\t")
    if not allow_colon:
        forbidden.add(":")
    if any(char in forbidden or ord(char) < 32 or char.isspace() for char in text):
        raise ReplicationError("INVALID_INPUT", f"{field} contains unsafe key characters")
    return text


def _require_stage(value: Any) -> str:
    if not isinstance(value, str) or _STAGE_RE.fullmatch(value) is None:
        raise ReplicationError("INVALID_INPUT", "stage must be a safe key component")
    return value


def _require_expected_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReplicationError("INVALID_INPUT", "expected_version must be a positive integer")
    return value


def _merge_invalidations(current: Sequence[str], incoming: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for item in [*current, *incoming]:
        if not isinstance(item, str) or not item:
            raise ReplicationError("INVALID_INPUT", "invalidate entries must be non-empty strings")
        if item not in result:
            result.append(item)
    return tuple(result)


def _snapshot_json(snapshot: JobSnapshot) -> str:
    return _canonical_json(snapshot.to_dict())


def _snapshot_meta(snapshot: JobSnapshot) -> tuple[str, str]:
    return (str(snapshot.current_script_revision or ""), str(snapshot.current_storyboard_revision or ""))


def _canonical_script_approval(
    value: Mapping[str, Any],
    *,
    revision: int,
    script_sha256: str,
) -> dict[str, Any]:
    """Freeze the user-confirmed exact lines in the script-approval CAS."""

    if not isinstance(value, Mapping):
        raise ReplicationError("INVALID_INPUT", "script_approval must be a mapping")
    required = {
        "contract",
        "revision",
        "script_sha256",
        "source_content_timeline_sha256",
        "line_contracts",
        "line_contracts_sha256",
        "visible_text_locks",
        "visible_text_locks_sha256",
    }
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if {"visible_text_locks", "visible_text_locks_sha256"} & set(missing):
        raise ReplicationError(
            "INVALID_INPUT",
            "script_approval visible text locks must be supplied together",
            details={"missing": missing},
        )
    if missing or unknown:
        raise ReplicationError(
            "INVALID_INPUT",
            "script_approval has an invalid shape",
            details={"missing": missing, "unknown": unknown},
        )
    if value.get("contract") != "approved-script-lines/v1":
        raise ReplicationError("INVALID_INPUT", "script_approval.contract is invalid")
    if value.get("revision") != revision:
        raise ReplicationError("INVALID_INPUT", "script_approval.revision must match revision")
    if value.get("script_sha256") != script_sha256:
        raise ReplicationError("INVALID_INPUT", "script_approval.script_sha256 must match expected_sha256")
    timeline_sha = _require_sha(
        value.get("source_content_timeline_sha256"),
        field="script_approval.source_content_timeline_sha256",
    )
    assert timeline_sha is not None
    lines = value.get("line_contracts")
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes, bytearray)):
        raise ReplicationError("INVALID_INPUT", "script_approval.line_contracts must be an array")
    try:
        from scripts.line_contract import validate_line_contracts

        canonical_lines = validate_line_contracts(lines)
    except Exception as exc:
        raise ReplicationError(
            "INVALID_INPUT",
            "script_approval.line_contracts must be canonical confirmed line contracts",
            details={"reason": str(exc)},
        ) from exc
    for line in canonical_lines:
        if line.get("source_content_timeline_sha256") != timeline_sha:
            raise ReplicationError(
                "INVALID_INPUT",
                "script_approval line timeline SHA differs from the frozen source timeline",
                details={"line_id": line.get("line_id")},
            )
    lines_sha = hashlib.sha256(
        _canonical_json(canonical_lines).encode("utf-8")
    ).hexdigest()
    if value.get("line_contracts_sha256") != lines_sha:
        raise ReplicationError(
            "INVALID_INPUT",
            "script_approval.line_contracts_sha256 does not match canonical line_contracts",
        )
    locks = value.get("visible_text_locks")
    if not isinstance(locks, Sequence) or isinstance(locks, (str, bytes, bytearray)):
        raise ReplicationError("INVALID_INPUT", "script_approval.visible_text_locks must be an array")
    try:
        from .visible_text_contract import canonicalize_visible_text_locks, visible_text_locks_sha256

        canonical_locks = canonicalize_visible_text_locks(locks)
        locks_sha = visible_text_locks_sha256(canonical_locks)
    except Exception as exc:
        raise ReplicationError(
            "INVALID_INPUT",
            "script_approval.visible_text_locks must be canonical visible text locks",
            details={"reason": str(exc)},
        ) from exc
    if value.get("visible_text_locks_sha256") != locks_sha:
        raise ReplicationError(
            "INVALID_INPUT",
            "script_approval.visible_text_locks_sha256 does not match canonical visible_text_locks",
        )
    return {
        "contract": "approved-script-lines/v1",
        "revision": revision,
        "script_sha256": script_sha256,
        "source_content_timeline_sha256": timeline_sha,
        "line_contracts": canonical_lines,
        "line_contracts_sha256": lines_sha,
        "visible_text_locks": canonical_locks,
        "visible_text_locks_sha256": locks_sha,
    }


_COMMON_LUA = r"""
local function redis_now_ms()
    local clock = redis.call('TIME')
    return tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
end

local function touch_keys(expiry, cleanup_key, stages_key, job_id, fixed)
    for _, key in ipairs(fixed) do
        if redis.call('EXISTS', key) == 1 then
            local current_ttl = redis.call('PTTL', key)
            if current_ttl < 0 or redis_now_ms() + current_ttl < expiry then
                redis.call('PEXPIREAT', key, expiry)
            end
        end
    end
    local fields = redis.call('HKEYS', stages_key)
    for _, field in ipairs(fields) do
        if string.sub(field, 1, 10) == '@leasekey:' then
            local lease_key = redis.call('HGET', stages_key, field)
            if lease_key and redis.call('EXISTS', lease_key) == 1 then
                local current_ttl = redis.call('PTTL', lease_key)
                if current_ttl < 0 or redis_now_ms() + current_ttl < expiry then
                    redis.call('PEXPIREAT', lease_key, expiry)
                end
            end
        end
    end
    redis.call('ZADD', cleanup_key, expiry, job_id)
end

local function retain_keys(expiry, stages_key, fixed)
    for _, key in ipairs(fixed) do
        if redis.call('EXISTS', key) == 1 then
            local current_ttl = redis.call('PTTL', key)
            if current_ttl < 0 or redis_now_ms() + current_ttl < expiry then
                redis.call('PEXPIREAT', key, expiry)
            end
        end
    end
    local fields = redis.call('HKEYS', stages_key)
    for _, field in ipairs(fields) do
        if string.sub(field, 1, 10) == '@leasekey:' then
            local lease_key = redis.call('HGET', stages_key, field)
            if lease_key and redis.call('EXISTS', lease_key) == 1 then
                local current_ttl = redis.call('PTTL', lease_key)
                if current_ttl < 0 or redis_now_ms() + current_ttl < expiry then
                    redis.call('PEXPIREAT', lease_key, expiry)
                end
            end
        end
    end
end

local function refresh_provider_due(providers_key, due_key, job_id, expiry)
    local fields = redis.call('HKEYS', providers_key)
    for _, field in ipairs(fields) do
        if string.sub(field, 1, 8) == '@status:' then
            local attempt_id = string.sub(field, 9)
            local status = redis.call('HGET', providers_key, field)
            local member = job_id .. ':' .. attempt_id
            if status == 'SUBMITTING' or status == 'RUNNING' or status == 'AMBIGUOUS' then
                redis.call('ZADD', due_key, expiry, member)
            else
                redis.call('ZREM', due_key, member)
            end
        end
    end
end

local function persist_snapshot(job_key, snapshot_json, version, script_revision, storyboard_revision)
    redis.call('HSET', job_key,
        'snapshot', snapshot_json,
        'version', tostring(version),
        'current_script_revision', script_revision,
        'current_storyboard_revision', storyboard_revision)
end

"""


_CREATE_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 1 then
    return {'CONFLICT'}
end
persist_snapshot(KEYS[1], ARGV[1], 1, ARGV[4], ARGV[5])
touch_keys(tonumber(ARGV[2]), KEYS[2], KEYS[3], ARGV[3], {KEYS[1]})
return {'OK', ARGV[1]}
"""


_SNAPSHOT_CAS_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[6], ARGV[7])
touch_keys(tonumber(ARGV[4]), KEYS[2], KEYS[3], ARGV[5], {KEYS[1], KEYS[3], KEYS[5], KEYS[6], KEYS[7], KEYS[8]})
refresh_provider_due(KEYS[5], KEYS[4], ARGV[5], tonumber(ARGV[4]))
return {'OK', ARGV[1]}
"""


_RECOVERY_CAS_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
if ARGV[5] == 'SET' then
    redis.call('SET', KEYS[2], ARGV[4])
else
    redis.call('DEL', KEYS[2])
end
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[8], ARGV[9])
touch_keys(tonumber(ARGV[6]), KEYS[3], KEYS[4], ARGV[7], {KEYS[1], KEYS[2], KEYS[4], KEYS[6], KEYS[7], KEYS[8], KEYS[9]})
if ARGV[5] == 'SET' then
    redis.call('PEXPIREAT', KEYS[2], tonumber(ARGV[10]))
end
refresh_provider_due(KEYS[6], KEYS[5], ARGV[7], tonumber(ARGV[6]))
return {'OK', ARGV[1]}
"""


_ARTIFACT_PUT_LUA = r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local existing = redis.call('HGET', KEYS[2], ARGV[1])
if existing then
    if existing == ARGV[2] then
        return {'NOOP', existing}
    end
    return {'CONFLICT'}
end
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('PEXPIREAT', KEYS[2], tonumber(ARGV[3]))
return {'OK', ARGV[2]}
"""


_REVISION_APPEND_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
local status_fields = redis.call('HKEYS', KEYS[4])
for _, field in ipairs(status_fields) do
    if string.sub(field, 1, 8) == '@status:' then
        local status = redis.call('HGET', KEYS[4], field)
        if status == 'SUBMITTING' or status == 'RUNNING' or status == 'AMBIGUOUS' then
            return {'REVISION_CONFLICT'}
        end
    end
end
local new_revision = tonumber(ARGV[4])
local current_revision = tonumber(ARGV[7]) or 0
if new_revision < current_revision then
    return {'REVISION_ORDER'}
end
local existing = redis.call('HGET', KEYS[2], ARGV[4])
if existing then
    if existing == ARGV[5] and new_revision == current_revision then
        return {'NOOP', redis.call('HGET', KEYS[1], 'snapshot')}
    end
    return {'REVISION_EXISTS'}
end
if new_revision <= current_revision then
    return {'REVISION_ORDER'}
end
redis.call('HSET', KEYS[2], ARGV[4], ARGV[5], '@sha:' .. ARGV[4], ARGV[6])
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[10], ARGV[11])
touch_keys(tonumber(ARGV[8]), KEYS[3], KEYS[5], ARGV[9], {KEYS[1], KEYS[2], KEYS[4], KEYS[5], KEYS[7], KEYS[8], KEYS[9]})
refresh_provider_due(KEYS[4], KEYS[6], ARGV[9], tonumber(ARGV[8]))
return {'OK', ARGV[1]}
"""


_APPROVE_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
local revision = ARGV[4]
if tonumber(redis.call('HGET', KEYS[1], ARGV[8]) or '-1') ~= tonumber(revision) then
    return {'APPROVAL_STALE'}
end
if redis.call('HGET', KEYS[2], revision) == false or redis.call('HGET', KEYS[2], '@sha:' .. revision) ~= ARGV[5] then
    return {'APPROVAL_STALE'}
end
if ARGV[11] ~= '' then
    local approval_field = '@approval:' .. revision
    local existing_approval = redis.call('HGET', KEYS[2], approval_field)
    if existing_approval and existing_approval ~= ARGV[11] then
        return {'APPROVAL_SIDECAR_CONFLICT'}
    end
    redis.call('HSET', KEYS[2], approval_field, ARGV[11])
end
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[9], ARGV[10])
touch_keys(tonumber(ARGV[6]), KEYS[3], KEYS[5], ARGV[7], {KEYS[1], KEYS[2], KEYS[4], KEYS[5], KEYS[7], KEYS[8], KEYS[9]})
refresh_provider_due(KEYS[4], KEYS[6], ARGV[7], tonumber(ARGV[6]))
return {'OK', ARGV[1]}
"""


_PROVIDER_BEGIN_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
local fields = redis.call('HKEYS', KEYS[2])
for _, field in ipairs(fields) do
    if string.sub(field, 1, 8) == '@status:' then
        local existing_id = string.sub(field, 9)
        local status = redis.call('HGET', KEYS[2], field)
        if status == 'SUBMITTING' or status == 'RUNNING' or status == 'AMBIGUOUS' then
            if redis.call('HGET', KEYS[2], '@operation:' .. existing_id) == ARGV[5] and
               redis.call('HGET', KEYS[2], '@request:' .. existing_id) == ARGV[6] and
               redis.call('HGET', KEYS[2], '@segment:' .. existing_id) == ARGV[7] and
               redis.call('HGET', KEYS[2], '@plan:' .. existing_id) == ARGV[8] then
                return {'DUPLICATE', existing_id}
            end
        end
    end
end
if redis.call('HEXISTS', KEYS[2], ARGV[4]) == 1 then
    return {'ATTEMPT_COLLISION'}
end
redis.call('HSET', KEYS[2], ARGV[4], ARGV[9],
    '@status:' .. ARGV[4], 'SUBMITTING',
    '@operation:' .. ARGV[4], ARGV[5],
    '@request:' .. ARGV[4], ARGV[6],
    '@segment:' .. ARGV[4], ARGV[7],
    '@plan:' .. ARGV[4], ARGV[8])
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[12], ARGV[13])
touch_keys(tonumber(ARGV[10]), KEYS[3], KEYS[4], ARGV[11], {KEYS[1], KEYS[2], KEYS[4], KEYS[6], KEYS[7], KEYS[8]})
refresh_provider_due(KEYS[2], KEYS[5], ARGV[11], tonumber(ARGV[10]))
retain_keys(tonumber(ARGV[14]), KEYS[4], {KEYS[1], KEYS[2], KEYS[4], KEYS[6], KEYS[7], KEYS[8]})
return {'OK', ARGV[9]}
"""


_PROVIDER_UPDATE_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
local attempt_id = ARGV[4]
local existing_json = redis.call('HGET', KEYS[2], attempt_id)
if not existing_json then
    return {'ATTEMPT_GONE'}
end
if redis.call('HGET', KEYS[2], '@operation:' .. attempt_id) ~= ARGV[6] or
   redis.call('HGET', KEYS[2], '@request:' .. attempt_id) ~= ARGV[7] or
   redis.call('HGET', KEYS[2], '@segment:' .. attempt_id) ~= ARGV[8] or
   redis.call('HGET', KEYS[2], '@plan:' .. attempt_id) ~= ARGV[9] then
    return {'IMMUTABLE'}
end
local old_status = redis.call('HGET', KEYS[2], '@status:' .. attempt_id)
if old_status == 'SUCCEEDED' or old_status == 'FAILED' then
    if existing_json == ARGV[5] then
        return {'NOOP', redis.call('HGET', KEYS[1], 'snapshot')}
    end
    return {'TERMINAL'}
end
local new_status = ARGV[10]
if new_status == 'SUBMITTING' or new_status == 'RUNNING' or new_status == 'AMBIGUOUS' then
    local fields = redis.call('HKEYS', KEYS[2])
    for _, field in ipairs(fields) do
        if string.sub(field, 1, 8) == '@status:' then
            local other_id = string.sub(field, 9)
            local status = redis.call('HGET', KEYS[2], field)
            if other_id ~= attempt_id and (status == 'SUBMITTING' or status == 'RUNNING' or status == 'AMBIGUOUS') and
               redis.call('HGET', KEYS[2], '@operation:' .. other_id) == ARGV[6] and
               redis.call('HGET', KEYS[2], '@request:' .. other_id) == ARGV[7] and
               redis.call('HGET', KEYS[2], '@segment:' .. other_id) == ARGV[8] and
               redis.call('HGET', KEYS[2], '@plan:' .. other_id) == ARGV[9] then
                return {'DUPLICATE_ACTIVE', other_id}
            end
        end
    end
end
redis.call('HSET', KEYS[2], attempt_id, ARGV[5], '@status:' .. attempt_id, new_status)
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[13], ARGV[14])
touch_keys(tonumber(ARGV[11]), KEYS[3], KEYS[4], ARGV[12], {KEYS[1], KEYS[2], KEYS[4], KEYS[6], KEYS[7], KEYS[8]})
refresh_provider_due(KEYS[2], KEYS[5], ARGV[12], tonumber(ARGV[11]))
if new_status == 'SUBMITTING' or new_status == 'RUNNING' or new_status == 'AMBIGUOUS' then
    retain_keys(tonumber(ARGV[15]), KEYS[4], {KEYS[1], KEYS[2], KEYS[4], KEYS[6], KEYS[7], KEYS[8]})
end
return {'OK', ARGV[1]}
"""


_PROVIDER_AUTHORIZATION_CONSUME_LUA = r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local clock = redis.call('TIME')
local now_ms = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
if now_ms >= tonumber(ARGV[5]) then
    return {'EXPIRED'}
end
if redis.call('HEXISTS', KEYS[2], ARGV[1]) == 0 then
    return {'ATTEMPT_MISSING'}
end
if redis.call('HGET', KEYS[2], '@operation:' .. ARGV[1]) ~= 'CreateVideo' or
   redis.call('HGET', KEYS[2], '@status:' .. ARGV[1]) ~= 'SUBMITTING' or
   redis.call('HGET', KEYS[2], '@request:' .. ARGV[1]) ~= ARGV[2] then
    return {'ATTEMPT_STALE'}
end
if redis.call('HGET', KEYS[3], ARGV[3]) then
    return {'CONSUMED'}
end
redis.call('HSET', KEYS[3], ARGV[3], ARGV[4])
redis.call('PEXPIREAT', KEYS[3], tonumber(ARGV[5]))
return {'OK'}
"""


_STAGE_CLAIM_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
local stage = ARGV[4]
local dedupe = ARGV[5]
local owner = ARGV[6]
local lease = redis.call('GET', KEYS[2])
local checkpoint = redis.call('HGET', KEYS[3], stage)
local now_ms = redis_now_ms()
local deadline = tonumber(redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':lease_expires_at_ms') or '0')
if lease and deadline > now_ms then
    if lease == ARGV[8] and checkpoint then
        return {'NOOP', checkpoint}
    end
    -- A user-confirmed script sidecar is an immutable input to the existing
    -- build_script stage.  It may legitimately re-enter after the draft
    -- attempt succeeded, even while that completed attempt's lease remains
    -- alive for duplicate-delivery fencing.  No other active stage may do so.
    if stage ~= 'build_script' or redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':status') ~= 'SUCCEEDED' or ARGV[15] ~= '1' then
        return {'CONFLICT'}
    end
    redis.call('DEL', KEYS[2])
end
local old_owner = redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':owner')
local old_dedupe = redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':dedupe')
if not lease or deadline <= now_ms then
    local token = owner .. string.char(0) .. dedupe
    local seen_prefix = '@seen:' .. stage .. ':'
    local fields = redis.call('HKEYS', KEYS[3])
    for _, field in ipairs(fields) do
        if string.sub(field, 1, string.len(seen_prefix)) == seen_prefix and redis.call('HGET', KEYS[3], field) == token then
            return {'RECLAIM_CONFLICT'}
        end
    end
end
local old_attempt = tonumber(redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':attempt') or '0')
local attempt = old_attempt + 1
if tonumber(ARGV[7]) ~= attempt then
    return {'ATTEMPT_STALE', tostring(attempt)}
end
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
redis.call('SET', KEYS[2], ARGV[8])
redis.call('HSET', KEYS[3], stage, ARGV[9],
    '@meta:' .. stage .. ':status', 'CLAIMED',
    '@meta:' .. stage .. ':owner', owner,
    '@meta:' .. stage .. ':dedupe', dedupe,
    '@meta:' .. stage .. ':attempt', tostring(attempt),
    '@meta:' .. stage .. ':lease_expires_at_ms', ARGV[10],
    '@leasekey:' .. stage, KEYS[2],
    '@seen:' .. stage .. ':' .. tostring(attempt), owner .. string.char(0) .. dedupe)
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[13], ARGV[14])
touch_keys(tonumber(ARGV[11]), KEYS[4], KEYS[3], ARGV[12], {KEYS[1], KEYS[3], KEYS[5], KEYS[7], KEYS[8], KEYS[9], KEYS[2]})
refresh_provider_due(KEYS[5], KEYS[6], ARGV[12], tonumber(ARGV[11]))
return {'OK', ARGV[9]}
"""


_STAGE_COMPLETE_LUA = _COMMON_LUA + r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {'GONE'}
end
local current_version = tonumber(redis.call('HGET', KEYS[1], 'version') or '-1')
local base_version = tonumber(ARGV[2])
local candidate_version = tonumber(ARGV[3])
local stage = ARGV[4]
local dedupe = ARGV[5]
local owner = ARGV[6]
local checkpoint = redis.call('HGET', KEYS[3], stage)
if not checkpoint then
    return {'STAGE_GONE'}
end
local status = redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':status')
local stored_owner = redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':owner')
local stored_dedupe = redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':dedupe')
if status == 'SUCCEEDED' and stored_owner == owner and stored_dedupe == dedupe then
    return {'NOOP', checkpoint}
end
local deadline = tonumber(redis.call('HGET', KEYS[3], '@meta:' .. stage .. ':lease_expires_at_ms') or '0')
if deadline <= redis_now_ms() then
    return {'LEASE_LOST'}
end
local lease = redis.call('GET', KEYS[2])
if not lease or lease ~= ARGV[12] then
    return {'LEASE_LOST'}
end
if status ~= 'CLAIMED' or stored_owner ~= owner or stored_dedupe ~= dedupe then
    return {'CONFLICT'}
end
if current_version ~= base_version or candidate_version ~= base_version + 1 then
    return {'STALE', tostring(current_version)}
end
redis.call('HSET', KEYS[3], stage, ARGV[7], '@meta:' .. stage .. ':status', 'SUCCEEDED')
persist_snapshot(KEYS[1], ARGV[1], candidate_version, ARGV[10], ARGV[11])
touch_keys(tonumber(ARGV[8]), KEYS[4], KEYS[3], ARGV[9], {KEYS[1], KEYS[3], KEYS[5], KEYS[7], KEYS[8], KEYS[9], KEYS[2]})
refresh_provider_due(KEYS[5], KEYS[6], ARGV[9], tonumber(ARGV[8]))
return {'OK', ARGV[7]}
"""


class RedisEphemeralJobStore(EphemeralJobStore):
    """Redis-backed, job-scoped active-state authority.

    Every write that can race with another worker is performed by a Lua script.
    Python constructs canonical JSON candidates; Lua only validates fences and
    stores the supplied bytes.

    The multi-key Lua mutations and cleanup fence are supported on Redis
    Standalone; Redis Cluster key-slot routing is intentionally out of scope.
    """

    def __init__(self, redis_client: Any, *, prefix: str = "usfr", provider_retention_ms: int = 300_000) -> None:
        self.redis = redis_client
        self.prefix = _require_key_component(prefix.rstrip(":"), field="prefix")
        self.provider_retention_ms = _require_retention_ms(provider_retention_ms)

    def _job_key(self, job_id: str) -> str:
        _require_key_component(job_id, field="job_id", allow_colon=False)
        return f"{self.prefix}:{job_id}:job"

    def _scripts_key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}:scripts"

    def _storyboards_key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}:storyboards"

    def _artifacts_key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}:artifacts"

    def _stages_key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}:stages"

    def _providers_key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}:providers"

    def _provider_authorizations_key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}:provider-authorizations"

    def _recovery_key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}:recovery"

    def _lease_key(self, job_id: str, stage: str) -> str:
        _require_stage(stage)
        return f"{self.prefix}:{job_id}:lease:{stage}"

    @property
    def _cleanup_due_key(self) -> str:
        return f"{self.prefix}:cleanup:due"

    @property
    def _provider_due_key(self) -> str:
        return f"{self.prefix}:provider:due"

    def _eval(self, script: str, keys: Sequence[str], args: Sequence[Any]) -> list[Any]:
        # Redis Standalone is the supported deployment mode for these
        # multi-key Lua mutations.  Add the per-job cleanup fence as an extra
        # key and check it inside the same EVAL, making cleanup acquisition a
        # real mutation fence rather than a request-local convention.
        eval_keys = list(keys)
        wrapped_script = script
        if eval_keys:
            job_key = str(eval_keys[0])
            marker = f"{self.prefix}:"
            suffix = ":job"
            if job_key.startswith(marker) and job_key.endswith(suffix):
                job_id = job_key[len(marker) : -len(suffix)]
                fence_key = f"{self.prefix}:{job_id}:lease:cleanup"
                eval_keys.append(fence_key)
                fence_index = len(eval_keys)
                wrapped_script = f"if redis.call('EXISTS', KEYS[{fence_index}]) == 1 then return {{'FENCED'}} end\n" + script
        return list(self.redis.eval(wrapped_script, len(eval_keys), *eval_keys, *args))

    @staticmethod
    def _status(result: Sequence[Any]) -> str:
        value = result[0]
        status = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        if status == "FENCED":
            raise StateConflictError("job cleanup fence is held")
        return status

    @staticmethod
    def _result_value(result: Sequence[Any], index: int = 1) -> Any:
        if len(result) <= index:
            return None
        value = result[index]
        return value.decode("utf-8") if isinstance(value, bytes) else value

    def _load_snapshot(self, job_id: str) -> JobSnapshot | None:
        raw = self.redis.hget(self._job_key(job_id), "snapshot")
        if raw is None:
            return None
        try:
            return JobSnapshot.from_dict(_json_load(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReplicationError("STATE_CORRUPT", "stored job snapshot is invalid") from exc

    def _require_snapshot(self, job_id: str) -> JobSnapshot:
        snapshot = self._load_snapshot(job_id)
        if snapshot is None:
            raise JobGoneError()
        return snapshot

    def _expiry(self, ttl_seconds: int | None, current: int | None = None) -> int:
        if ttl_seconds is None:
            if current is None:
                raise ReplicationError("INVALID_INPUT", "an expiry is required")
            return int(current)
        return _now_ms() + (_require_ttl(ttl_seconds) * 1000)

    def _stage_expiry(self, ttl_seconds: int, current: int) -> tuple[int, int]:
        ttl = _require_ttl(ttl_seconds)
        now = _now_ms()
        return now + ttl * 1000, max(current, now + ttl * 1000)

    def _base_keys(self, job_id: str) -> list[str]:
        return [
            self._job_key(job_id),
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
            self._stages_key(job_id),
            self._providers_key(job_id),
            self._recovery_key(job_id),
        ]

    def create_job(
        self,
        *,
        slots_manifest: Mapping[str, Any],
        capability_token_hash: str,
        ttl_seconds: int,
        correlation_id: str | None = None,
    ) -> JobSnapshot:
        if not isinstance(slots_manifest, Mapping):
            raise ReplicationError("INVALID_INPUT", "slots_manifest must be a mapping")
        _require_sha(capability_token_hash, field="capability_token_hash")
        ttl = _require_ttl(ttl_seconds)
        job_id = uuid.uuid4().hex
        expires_at_ms = _now_ms() + ttl * 1000
        snapshot = JobSnapshot.new(
            job_id=job_id,
            capability_token_hash=capability_token_hash,
            slots_manifest=dict(slots_manifest),
            expires_at_ms=expires_at_ms,
        )
        script_revision, storyboard_revision = _snapshot_meta(snapshot)
        result = self._eval(
            _CREATE_LUA,
            [self._job_key(job_id), self._cleanup_due_key, self._stages_key(job_id)],
            [_snapshot_json(snapshot), expires_at_ms, job_id, script_revision, storyboard_revision],
        )
        status = self._status(result)
        if status == "CONFLICT":
            raise StateConflictError("job id collision")
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "unable to create job")
        return snapshot

    def get_job(self, job_id: str) -> JobSnapshot | None:
        _require_nonempty_text(job_id, field="job_id")
        return self._load_snapshot(job_id)

    def cas_transition(
        self,
        *,
        job_id: str,
        expected_version: int,
        command: str,
        updates: Mapping[str, Any] | None = None,
        invalidate: Sequence[str] = (),
        ttl_seconds: int | None = None,
    ) -> JobSnapshot:
        _require_nonempty_text(job_id, field="job_id")
        _require_nonempty_text(command, field="command")
        _require_expected_version(expected_version)
        current = self._require_snapshot(job_id)
        if expected_version != current.version:
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": current.version})
        update_values = dict(updates or {})
        forbidden = {"job_id", "version", "capability_token_hash", "capability_token_version", "expires_at_ms", "invalidated"}
        if forbidden.intersection(update_values):
            raise ReplicationError("INVALID_INPUT", "immutable JobSnapshot fields cannot be updated")
        unknown = set(update_values) - _SNAPSHOT_MUTABLE_FIELDS
        if unknown:
            raise ReplicationError("INVALID_INPUT", "unknown JobSnapshot update field", details={"fields": sorted(unknown)})
        payload = current.to_dict()
        for field, value in update_values.items():
            if field in {"approved_script_sha256", "approved_storyboard_sha256"}:
                _require_sha(value, field=field, optional=True)
            if field in {"current_script_revision", "current_storyboard_revision"} and value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ReplicationError("INVALID_INPUT", f"{field} must be a positive integer or null")
            if field == "slots_manifest" and not isinstance(value, Mapping):
                raise ReplicationError("INVALID_INPUT", "slots_manifest must be a mapping")
            if field == "final_ref" and value is not None and not isinstance(value, Mapping):
                raise ReplicationError("INVALID_INPUT", "final_ref must be a mapping or null")
            if field in {"state", "review_route"} and value is not None and not isinstance(value, str):
                raise ReplicationError("INVALID_INPUT", f"{field} must be a string or null")
            payload[field] = value
        payload["invalidated"] = list(_merge_invalidations(current.invalidated, invalidate))
        payload["version"] = current.version + 1
        payload["expires_at_ms"] = self._expiry(ttl_seconds, current.expires_at_ms)
        candidate = JobSnapshot.from_dict(payload)
        keys = [
            self._job_key(job_id),
            self._cleanup_due_key,
            self._stages_key(job_id),
            self._provider_due_key,
            self._providers_key(job_id),
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
        ]
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        result = self._eval(
            _SNAPSHOT_CAS_LUA,
            keys,
            [
                _snapshot_json(candidate),
                expected_version,
                candidate.version,
                candidate.expires_at_ms,
                job_id,
                script_revision,
                storyboard_revision,
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "STALE":
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": self._result_value(result)})
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "snapshot CAS failed")
        return candidate

    def append_revision(
        self,
        *,
        job_id: str,
        kind: Literal["script", "storyboard"],
        expected_version: int,
        manifest: Mapping[str, Any],
        invalidate_downstream: bool,
        ttl_seconds: int,
    ) -> JobSnapshot:
        if kind not in {"script", "storyboard"}:
            raise ReplicationError("INVALID_INPUT", "kind must be script or storyboard")
        manifest_obj = manifest if isinstance(manifest, RevisionManifest) else None
        if manifest_obj is not None:
            manifest = manifest_obj.to_dict()
        if not isinstance(manifest, Mapping):
            raise ReplicationError("INVALID_INPUT", "manifest must be a mapping")
        revision = manifest.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ReplicationError("INVALID_INPUT", "manifest revision must be a positive integer")
        sha256 = _require_sha(manifest.get("sha256"), field="manifest.sha256")
        assert sha256 is not None
        _require_ttl(ttl_seconds)
        _require_expected_version(expected_version)
        current = self._require_snapshot(job_id)
        if expected_version != current.version:
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": current.version})
        current_revision = current.current_script_revision if kind == "script" else current.current_storyboard_revision
        payload = current.to_dict()
        payload["version"] = current.version + 1
        payload["expires_at_ms"] = self._expiry(ttl_seconds, current.expires_at_ms)
        payload["invalidated"] = list(current.invalidated)
        if kind == "script":
            payload["current_script_revision"] = revision
            payload["approved_script_sha256"] = None
            payload["current_storyboard_revision"] = None
            payload["approved_storyboard_sha256"] = None
            if invalidate_downstream:
                payload["invalidated"] = list(
                    _merge_invalidations(
                        current.invalidated,
                        ("storyboard", "segment_plan", "prompt_audit", "provider_plan", "assembly", "qc"),
                    )
                )
            revisions_key = self._scripts_key(job_id)
        else:
            payload["current_storyboard_revision"] = revision
            payload["approved_storyboard_sha256"] = None
            if invalidate_downstream:
                payload["invalidated"] = list(_merge_invalidations(current.invalidated, ("prompt_audit", "provider_plan", "assembly", "qc")))
            revisions_key = self._storyboards_key(job_id)
        candidate = JobSnapshot.from_dict(payload)
        keys = [
            self._job_key(job_id),
            revisions_key,
            self._cleanup_due_key,
            self._providers_key(job_id),
            self._stages_key(job_id),
            self._provider_due_key,
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
        ]
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        result = self._eval(
            _REVISION_APPEND_LUA,
            keys,
            [
                _snapshot_json(candidate),
                expected_version,
                candidate.version,
                str(revision),
                _canonical_json(dict(manifest)),
                sha256,
                current_revision or 0,
                candidate.expires_at_ms,
                job_id,
                script_revision,
                storyboard_revision,
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "STALE":
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": self._result_value(result)})
        if status == "REVISION_CONFLICT":
            raise RevisionConflictError()
        if status in {"REVISION_EXISTS", "REVISION_ORDER"}:
            raise StateConflictError("revision must be monotonic and immutable")
        if status == "NOOP":
            raw = self._result_value(result)
            return JobSnapshot.from_dict(_json_load(raw))
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "revision append failed")
        if manifest_obj is not None:
            # Keep the immutable revision records useful to browse clients.
            for prior in self.list_revisions(job_id, kind):
                if prior.revision < revision and prior.status != "SUPERSEDED":
                    prior_payload = prior.to_dict()
                    prior_payload["status"] = "SUPERSEDED"
                    self.redis.hset(revisions_key, str(prior.revision), _canonical_json(prior_payload))
        return candidate

    @staticmethod
    def _revision_from_dict(value: Mapping[str, Any]) -> RevisionManifest:
        payload = dict(value)
        request = payload.get("request")
        if isinstance(request, Mapping):
            payload["request"] = RevisionRequest(**dict(request))
        payload["changed_cut_ids"] = tuple(payload.get("changed_cut_ids") or ())
        payload["reused_cut_ids"] = tuple(payload.get("reused_cut_ids") or ())
        cuts = payload.get("cut_images") or ()
        payload["cut_images"] = tuple(StoryboardCutRef(**dict(item)) for item in cuts if isinstance(item, Mapping))
        payload.setdefault("created_at", "")
        payload.setdefault("status", "CURRENT")
        return RevisionManifest(**payload)

    def list_revisions(self, job_id: str, kind: Literal["script", "storyboard"]) -> tuple[RevisionManifest, ...]:
        if kind not in {"script", "storyboard"}:
            raise ReplicationError("INVALID_INPUT", "kind must be script or storyboard")
        key = self._scripts_key(job_id) if kind == "script" else self._storyboards_key(job_id)
        values = self.redis.hgetall(key)
        rows = []
        for field, raw in values.items():
            field_text = field.decode() if isinstance(field, bytes) else str(field)
            if field_text.startswith("@"):
                continue
            try:
                rows.append(self._revision_from_dict(_json_load(raw)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ReplicationError("STATE_CORRUPT", "stored revision is invalid") from exc
        return tuple(sorted(rows, key=lambda item: item.revision))

    def get_current_revision(self, job_id: str, kind: Literal["script", "storyboard"]) -> RevisionManifest | None:
        snapshot = self._require_snapshot(job_id)
        revision = snapshot.current_script_revision if kind == "script" else snapshot.current_storyboard_revision
        if revision is None:
            return None
        key = self._scripts_key(job_id) if kind == "script" else self._storyboards_key(job_id)
        raw = self.redis.hget(key, str(revision))
        return self._revision_from_dict(_json_load(raw)) if raw is not None else None

    def get_script_approval(self, job_id: str, revision: int) -> Mapping[str, Any] | None:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ReplicationError("INVALID_INPUT", "revision must be a positive integer")
        snapshot = self._require_snapshot(job_id)
        raw = self.redis.hget(self._scripts_key(job_id), f"@approval:{revision}")
        if raw is None:
            return None
        try:
            value = _json_load(raw)
            if not isinstance(value, Mapping):
                raise TypeError("script approval must be an object")
            script_sha = _require_sha(value.get("script_sha256"), field="script_approval.script_sha256")
            assert script_sha is not None
            approved = _canonical_script_approval(
                value,
                revision=revision,
                script_sha256=script_sha,
            )
        except (ReplicationError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ReplicationError):
                raise ReplicationError("STATE_CORRUPT", "stored script approval is invalid") from exc
            raise ReplicationError("STATE_CORRUPT", "stored script approval is invalid") from exc
        if snapshot.current_script_revision == revision and snapshot.approved_script_sha256 != approved["script_sha256"]:
            raise ReplicationError("STATE_CORRUPT", "stored script approval is not bound to the approved revision")
        return approved

    def touch_review_ttl(self, job_id: str, ttl_seconds: int) -> JobSnapshot:
        current = self._require_snapshot(job_id)
        expiry = self._expiry(ttl_seconds, current.expires_at_ms)
        for key in self._base_keys(job_id):
            if self.redis.exists(key):
                self.redis.pexpireat(key, expiry)
        self.redis.zadd(self._cleanup_due_key, {job_id: expiry})
        return current

    def get_recovery_checkpoint(self, job_id: str) -> RecoveryCheckpoint | None:
        self._require_snapshot(job_id)
        raw = self.redis.get(self._recovery_key(job_id))
        if raw is None:
            return None
        try:
            value = _json_load(raw)
            if not isinstance(value, Mapping):
                raise TypeError("checkpoint must be an object")
            return RecoveryCheckpoint.from_dict(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReplicationError("STATE_CORRUPT", "stored recovery checkpoint is invalid") from exc

    def put_artifact(self, *, job_id: str, artifact: ArtifactRef) -> ArtifactRef:
        if not isinstance(artifact, ArtifactRef):
            raise ReplicationError("INVALID_INPUT", "artifact must be an ArtifactRef")
        _require_nonempty_text(artifact.artifact_id, field="artifact_id")
        _require_sha(artifact.sha256, field="artifact.sha256")
        snapshot = self._require_snapshot(job_id)
        physical_job_expiry = self.redis.execute_command(
            "PEXPIRETIME", self._job_key(job_id)
        )
        if not isinstance(physical_job_expiry, (int, float)) or physical_job_expiry < 1:
            physical_job_expiry = snapshot.expires_at_ms
        payload = _canonical_json(artifact.to_dict())
        result = self._eval(
            _ARTIFACT_PUT_LUA,
            [self._job_key(job_id), self._artifacts_key(job_id)],
            [artifact.artifact_id, payload, int(physical_job_expiry)],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "CONFLICT":
            raise StateConflictError("artifact identity is immutable")
        if status not in {"OK", "NOOP"}:
            raise ReplicationError("STORE_ERROR", "artifact publication could not be recorded")
        return artifact

    def get_artifact(self, job_id: str, artifact_id: str) -> ArtifactRef | None:
        self._require_snapshot(job_id)
        _require_nonempty_text(artifact_id, field="artifact_id")
        raw = self.redis.hget(self._artifacts_key(job_id), artifact_id)
        if raw is None:
            return None
        try:
            return ArtifactRef(**dict(_json_load(raw)))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReplicationError("STATE_CORRUPT", "stored artifact reference is invalid") from exc

    def list_artifacts(self, job_id: str) -> tuple[ArtifactRef, ...]:
        self._require_snapshot(job_id)
        values = self.redis.hgetall(self._artifacts_key(job_id)) or {}
        rows: list[ArtifactRef] = []
        try:
            for raw in values.values():
                rows.append(ArtifactRef(**dict(_json_load(raw))))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReplicationError("STATE_CORRUPT", "stored artifact reference is invalid") from exc
        return tuple(sorted(rows, key=lambda item: item.artifact_id))

    def get_stage_checkpoint(self, job_id: str, stage: str) -> StageCheckpoint | None:
        self._require_snapshot(job_id)
        raw = self.redis.hget(self._stages_key(job_id), _require_stage(stage))
        return self._checkpoint_from_raw(raw) if raw is not None else None

    def _write_recovery_checkpoint(
        self,
        *,
        job_id: str,
        expected_version: int,
        checkpoint: RecoveryCheckpoint | None,
        ttl_seconds: int,
    ) -> JobSnapshot:
        _require_expected_version(expected_version)
        _require_ttl(ttl_seconds)
        current = self._require_snapshot(job_id)
        if current.version != expected_version:
            raise StateConflictError(
                details={"expected_version": expected_version, "actual_version": current.version}
            )
        if checkpoint is not None and not isinstance(checkpoint, RecoveryCheckpoint):
            raise ReplicationError("INVALID_INPUT", "checkpoint must be a RecoveryCheckpoint")
        if checkpoint is not None and checkpoint.candidate is not None:
            object_key = checkpoint.candidate.artifact_ref.get("object_key")
            expected_prefix = f"temporary/{job_id}/recovery/"
            if not isinstance(object_key, str) or not object_key.startswith(expected_prefix):
                raise ReplicationError(
                    "INVALID_INPUT",
                    "recovery candidate must use the job temporary recovery prefix",
                )
        payload = current.to_dict()
        payload["version"] = current.version + 1
        payload["expires_at_ms"] = self._expiry(ttl_seconds, current.expires_at_ms)
        candidate = JobSnapshot.from_dict(payload)
        physical_job_expiry = self.redis.execute_command(
            "PEXPIRETIME", self._job_key(job_id)
        )
        if not isinstance(physical_job_expiry, (int, float)) or physical_job_expiry < 1:
            physical_job_expiry = candidate.expires_at_ms
        recovery_expiry = max(candidate.expires_at_ms, int(physical_job_expiry))
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        result = self._eval(
            _RECOVERY_CAS_LUA,
            [
                self._job_key(job_id),
                self._recovery_key(job_id),
                self._cleanup_due_key,
                self._stages_key(job_id),
                self._provider_due_key,
                self._providers_key(job_id),
                self._scripts_key(job_id),
                self._storyboards_key(job_id),
                self._artifacts_key(job_id),
            ],
            [
                _snapshot_json(candidate),
                expected_version,
                candidate.version,
                _canonical_json(checkpoint.to_dict()) if checkpoint is not None else "",
                "SET" if checkpoint is not None else "DEL",
                candidate.expires_at_ms,
                job_id,
                script_revision,
                storyboard_revision,
                recovery_expiry,
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "STALE":
            raise StateConflictError(
                details={"expected_version": expected_version, "actual_version": self._result_value(result)}
            )
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "recovery checkpoint CAS failed")
        return candidate

    def put_recovery_checkpoint(
        self,
        *,
        job_id: str,
        expected_version: int,
        checkpoint: RecoveryCheckpoint,
        ttl_seconds: int,
    ) -> JobSnapshot:
        return self._write_recovery_checkpoint(
            job_id=job_id,
            expected_version=expected_version,
            checkpoint=checkpoint,
            ttl_seconds=ttl_seconds,
        )

    def clear_recovery_checkpoint(
        self,
        *,
        job_id: str,
        expected_version: int,
        ttl_seconds: int,
    ) -> JobSnapshot:
        return self._write_recovery_checkpoint(
            job_id=job_id,
            expected_version=expected_version,
            checkpoint=None,
            ttl_seconds=ttl_seconds,
        )

    def approve_revision(
        self,
        *,
        job_id: str,
        kind: Literal["script", "storyboard"],
        revision: int,
        expected_version: int,
        expected_sha256: str,
        script_approval: Mapping[str, Any] | None = None,
        ttl_seconds: int,
    ) -> JobSnapshot:
        if kind not in {"script", "storyboard"}:
            raise ReplicationError("INVALID_INPUT", "kind must be script or storyboard")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ReplicationError("INVALID_INPUT", "revision must be a positive integer")
        _require_sha(expected_sha256, field="expected_sha256")
        if script_approval is not None and kind != "script":
            raise ReplicationError("INVALID_INPUT", "script_approval is valid only for script revisions")
        canonical_approval = (
            _canonical_script_approval(
                script_approval,
                revision=revision,
                script_sha256=expected_sha256,
            )
            if script_approval is not None
            else None
        )
        _require_ttl(ttl_seconds)
        _require_expected_version(expected_version)
        current = self._require_snapshot(job_id)
        if expected_version != current.version:
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": current.version})
        payload = current.to_dict()
        payload["version"] = current.version + 1
        payload["expires_at_ms"] = self._expiry(ttl_seconds, current.expires_at_ms)
        field_revision = "current_script_revision" if kind == "script" else "current_storyboard_revision"
        field_approved = "approved_script_sha256" if kind == "script" else "approved_storyboard_sha256"
        payload[field_approved] = expected_sha256
        candidate = JobSnapshot.from_dict(payload)
        revisions_key = self._scripts_key(job_id) if kind == "script" else self._storyboards_key(job_id)
        keys = [
            self._job_key(job_id),
            revisions_key,
            self._cleanup_due_key,
            self._providers_key(job_id),
            self._stages_key(job_id),
            self._provider_due_key,
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
        ]
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        result = self._eval(
            _APPROVE_LUA,
            keys,
            [
                _snapshot_json(candidate),
                expected_version,
                candidate.version,
                revision,
                expected_sha256,
                candidate.expires_at_ms,
                job_id,
                field_revision,
                script_revision,
                storyboard_revision,
                _canonical_json(canonical_approval) if canonical_approval is not None else "",
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "STALE":
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": self._result_value(result)})
        if status == "APPROVAL_STALE":
            raise ApprovalStaleError(details={"revision": revision})
        if status == "APPROVAL_SIDECAR_CONFLICT":
            raise StateConflictError("script approval sidecar is immutable")
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "revision approval failed")
        raw_manifest = self.redis.hget(revisions_key, str(revision))
        if raw_manifest is not None:
            try:
                approved_manifest = self._revision_from_dict(_json_load(raw_manifest)).to_dict()
            except (TypeError, ValueError):
                approved_manifest = None
            if approved_manifest is not None:
                approved_manifest["status"] = "APPROVED"
                self.redis.hset(revisions_key, str(revision), _canonical_json(approved_manifest))
        return candidate

    def begin_provider_attempt(
        self,
        *,
        job_id: str,
        expected_version: int,
        operation: Literal["CreateAsset", "CreateVideo"],
        request_sha256: str,
        segment_id: str | None = None,
        segment_plan_sha256: str | None = None,
    ) -> ProviderAttempt:
        if operation not in _PROVIDER_OPERATIONS:
            raise ReplicationError("INVALID_INPUT", "unsupported provider operation")
        _require_sha(request_sha256, field="request_sha256")
        if (segment_id is None) != (segment_plan_sha256 is None):
            raise ReplicationError("INVALID_INPUT", "segment_id and segment_plan_sha256 must be supplied together")
        if segment_id is not None:
            _require_nonempty_text(segment_id, field="segment_id")
            _require_sha(segment_plan_sha256, field="segment_plan_sha256")
        _require_expected_version(expected_version)
        current = self._require_snapshot(job_id)
        if expected_version != current.version:
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": current.version})
        payload = current.to_dict()
        payload["version"] = current.version + 1
        attempt_id = uuid.uuid4().hex
        attempt = ProviderAttempt(
            attempt_id=attempt_id,
            operation=operation,
            request_sha256=request_sha256,
            status="SUBMITTING",
            segment_id=segment_id,
            segment_plan_sha256=segment_plan_sha256,
        )
        candidate = JobSnapshot.from_dict(payload)
        # Attempt creation has no ttl argument; preserve the current absolute expiry.
        keys = [
            self._job_key(job_id),
            self._providers_key(job_id),
            self._cleanup_due_key,
            self._stages_key(job_id),
            self._provider_due_key,
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
        ]
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        result = self._eval(
            _PROVIDER_BEGIN_LUA,
            keys,
            [
                _snapshot_json(candidate),
                expected_version,
                candidate.version,
                attempt_id,
                operation,
                request_sha256,
                segment_id or "",
                segment_plan_sha256 or "",
                _canonical_json(attempt.to_dict()),
                current.expires_at_ms,
                job_id,
                script_revision,
                storyboard_revision,
                current.expires_at_ms + self.provider_retention_ms,
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "STALE":
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": self._result_value(result)})
        if status == "DUPLICATE":
            raise IdempotencyConflictError(details={"attempt_id": self._result_value(result)})
        if status == "ATTEMPT_COLLISION":
            # A UUID collision is vanishingly unlikely; surface a conflict without overwriting.
            raise StateConflictError("provider attempt id collision")
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "provider attempt reservation failed")
        return attempt

    def list_provider_attempts(self, job_id: str) -> tuple[ProviderAttempt, ...]:
        """Read every retained provider attempt without changing job authority."""

        self._require_snapshot(job_id)
        try:
            raw_attempts = self.redis.hgetall(self._providers_key(job_id))
        except Exception as error:
            raise ReplicationError("STORE_ERROR", "provider attempt lookup failed") from error
        attempts: list[ProviderAttempt] = []
        for raw_id, raw_value in raw_attempts.items():
            attempt_id = raw_id.decode("utf-8") if isinstance(raw_id, bytes) else str(raw_id)
            if attempt_id.startswith("@"):
                continue
            try:
                decoded = _json_load(raw_value)
                attempt = ProviderAttempt.from_dict(decoded)
                self._validate_attempt(attempt, allow_prepared=True)
            except (TypeError, ValueError, ReplicationError) as error:
                raise ReplicationError("STORE_ERROR", "stored provider attempt is invalid") from error
            if attempt.attempt_id != attempt_id:
                raise ReplicationError("STORE_ERROR", "stored provider attempt identity is invalid")
            attempts.append(attempt)
        return tuple(sorted(attempts, key=lambda item: item.attempt_id))

    def update_provider_attempt(
        self,
        *,
        job_id: str,
        expected_version: int,
        attempt: ProviderAttempt,
        ttl_seconds: int,
    ) -> JobSnapshot:
        if not isinstance(attempt, ProviderAttempt):
            raise ReplicationError("INVALID_INPUT", "attempt must be a ProviderAttempt")
        self._validate_attempt(attempt, allow_prepared=False)
        _require_ttl(ttl_seconds)
        _require_expected_version(expected_version)
        current = self._require_snapshot(job_id)
        if expected_version != current.version:
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": current.version})
        payload = current.to_dict()
        payload["version"] = current.version + 1
        payload["expires_at_ms"] = self._expiry(ttl_seconds, current.expires_at_ms)
        candidate = JobSnapshot.from_dict(payload)
        keys = [
            self._job_key(job_id),
            self._providers_key(job_id),
            self._cleanup_due_key,
            self._stages_key(job_id),
            self._provider_due_key,
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
        ]
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        result = self._eval(
            _PROVIDER_UPDATE_LUA,
            keys,
            [
                _snapshot_json(candidate),
                expected_version,
                candidate.version,
                attempt.attempt_id,
                _canonical_json(attempt.to_dict()),
                attempt.operation,
                attempt.request_sha256,
                attempt.segment_id or "",
                attempt.segment_plan_sha256 or "",
                attempt.status,
                candidate.expires_at_ms,
                job_id,
                script_revision,
                storyboard_revision,
                candidate.expires_at_ms + self.provider_retention_ms,
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "STALE":
            raise StateConflictError(details={"expected_version": expected_version, "actual_version": self._result_value(result)})
        if status in {"ATTEMPT_GONE", "IMMUTABLE", "TERMINAL", "DUPLICATE_ACTIVE"}:
            raise StateConflictError("provider attempt does not exist or immutable identity changed")
        if status == "NOOP":
            return JobSnapshot.from_dict(_json_load(self._result_value(result)))
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "provider attempt update failed")
        return candidate

    def consume_provider_authorization_nonce(
        self,
        *,
        job_id: str,
        attempt_id: str,
        request_sha256: str,
        nonce: str,
        authorization_sha256: str,
        expires_at_ms: int,
    ) -> bool:
        """Use Redis as the cross-worker, one-time paid-request authority."""

        _require_nonempty_text(attempt_id, field="attempt_id")
        _require_sha(request_sha256, field="request_sha256")
        _require_key_component(nonce, field="nonce", allow_colon=False)
        _require_sha(authorization_sha256, field="authorization_sha256")
        if isinstance(expires_at_ms, bool) or not isinstance(expires_at_ms, int) or expires_at_ms <= _now_ms():
            return False
        result = self._eval(
            _PROVIDER_AUTHORIZATION_CONSUME_LUA,
            [self._job_key(job_id), self._providers_key(job_id), self._provider_authorizations_key(job_id)],
            [attempt_id, request_sha256, nonce, authorization_sha256, expires_at_ms],
        )
        status = self._status(result)
        if status == "OK":
            return True
        if status in {"GONE", "EXPIRED", "ATTEMPT_MISSING", "ATTEMPT_STALE", "CONSUMED"}:
            return False
        raise ReplicationError("STORE_ERROR", "provider authorization nonce could not be consumed")

    @staticmethod
    def _validate_attempt(attempt: ProviderAttempt, *, allow_prepared: bool) -> None:
        if not attempt.attempt_id:
            raise ReplicationError("INVALID_INPUT", "attempt_id must be non-empty")
        if attempt.operation not in _PROVIDER_OPERATIONS:
            raise ReplicationError("INVALID_INPUT", "unsupported provider operation")
        _require_sha(attempt.request_sha256, field="request_sha256")
        if attempt.status not in _PROVIDER_STATUSES or (not allow_prepared and attempt.status == "PREPARED"):
            raise ReplicationError("INVALID_INPUT", "unsupported provider attempt status")
        if (attempt.segment_id is None) != (attempt.segment_plan_sha256 is None):
            raise ReplicationError("INVALID_INPUT", "segment identity must be supplied together")
        if attempt.segment_id is not None:
            _require_nonempty_text(attempt.segment_id, field="segment_id")
            _require_sha(attempt.segment_plan_sha256, field="segment_plan_sha256")
        if attempt.provider_task_id is not None:
            _require_nonempty_text(attempt.provider_task_id, field="provider_task_id")
        if attempt.response_sha256 is not None:
            _require_sha(attempt.response_sha256, field="response_sha256")

    def claim_stage(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        owner: str,
        ttl_seconds: int,
    ) -> StageCheckpoint:
        for retry in range(2):
            try:
                return self._claim_stage_once(
                    job_id=job_id,
                    stage=stage,
                    dedupe_key=dedupe_key,
                    owner=owner,
                    ttl_seconds=ttl_seconds,
                )
            except _StageAttemptStale:
                if retry == 1:
                    raise StateConflictError()
        raise StateConflictError()

    def _claim_stage_once(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        owner: str,
        ttl_seconds: int,
    ) -> StageCheckpoint:
        _require_stage(stage)
        _require_key_component(dedupe_key, field="dedupe_key")
        _require_key_component(owner, field="owner")
        _require_ttl(ttl_seconds)
        current = self._require_snapshot(job_id)
        stage_key = self._stages_key(job_id)
        existing_raw = self.redis.hget(stage_key, stage)
        existing = self._checkpoint_from_raw(existing_raw) if existing_raw else None
        recovery_reclaim = self._is_verified_script_recovery_claim(
            job_id=job_id,
            stage=stage,
            dedupe_key=dedupe_key,
            snapshot=current,
            existing=existing,
        )
        now_ms = _now_ms()
        logical_deadline = int(self.redis.hget(stage_key, f"@meta:{stage}:lease_expires_at_ms") or 0)
        lease_is_active = bool(self.redis.exists(self._lease_key(job_id, stage))) and logical_deadline > now_ms
        attempt_number = (existing.attempt if lease_is_active else existing.attempt + 1) if existing is not None else 1
        payload = current.to_dict()
        payload["version"] = current.version + 1
        logical_deadline, payload["expires_at_ms"] = self._stage_expiry(ttl_seconds, current.expires_at_ms)
        candidate = JobSnapshot.from_dict(payload)
        checkpoint = StageCheckpoint(stage=stage, dedupe_key=dedupe_key, status="CLAIMED", attempt=attempt_number, owner=owner)
        lease = {"owner": owner, "dedupe_key": dedupe_key, "attempt": attempt_number}
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        keys = [
            self._job_key(job_id),
            self._lease_key(job_id, stage),
            stage_key,
            self._cleanup_due_key,
            self._providers_key(job_id),
            self._provider_due_key,
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
        ]
        result = self._eval(
            _STAGE_CLAIM_LUA,
            keys,
            [
                _snapshot_json(candidate),
                current.version,
                candidate.version,
                stage,
                dedupe_key,
                owner,
                attempt_number,
                _canonical_json(lease),
                _canonical_json({**checkpoint.__dict__, "output_artifact_ids": list(checkpoint.output_artifact_ids)}),
                logical_deadline,
                candidate.expires_at_ms,
                job_id,
                script_revision,
                storyboard_revision,
                "1" if recovery_reclaim else "0",
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status in {"CONFLICT", "RECLAIM_CONFLICT"}:
            raise StateConflictError()
        if status == "NOOP":
            return self._checkpoint_from_raw(self._result_value(result))
        if status == "ATTEMPT_STALE":
            raise _StageAttemptStale()
        if status == "STALE":
            raise StateConflictError()
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "stage claim failed")
        return checkpoint

    def _is_verified_script_recovery_claim(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        snapshot: JobSnapshot,
        existing: StageCheckpoint | None,
    ) -> bool:
        """Authorize only a current CAS-sidecar recovery of build_script."""

        if (
            stage != "build_script"
            or existing is None
            or existing.status != "SUCCEEDED"
            or existing.dedupe_key == dedupe_key
            or snapshot.current_script_revision is None
            or not snapshot.approved_script_sha256
        ):
            return False
        approval = self.get_script_approval(job_id, snapshot.current_script_revision)
        if approval is None:
            return False
        from .ephemeral_driver import script_recovery_dedupe

        return dedupe_key == script_recovery_dedupe(job_id, snapshot, approval)

    def complete_stage(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        owner: str,
        output_artifact_ids: Sequence[str],
        ttl_seconds: int,
    ) -> StageCheckpoint:
        _require_stage(stage)
        _require_key_component(dedupe_key, field="dedupe_key")
        _require_key_component(owner, field="owner")
        _require_ttl(ttl_seconds)
        if not isinstance(output_artifact_ids, Sequence) or isinstance(output_artifact_ids, (str, bytes)):
            raise ReplicationError("INVALID_INPUT", "output_artifact_ids must be a sequence")
        outputs: list[str] = []
        for artifact_id in output_artifact_ids:
            outputs.append(_require_nonempty_text(artifact_id, field="output_artifact_id"))
        current = self._require_snapshot(job_id)
        _, job_expiry = self._stage_expiry(ttl_seconds, current.expires_at_ms)
        payload = current.to_dict()
        payload["version"] = current.version + 1
        payload["expires_at_ms"] = job_expiry
        candidate = JobSnapshot.from_dict(payload)
        checkpoint = StageCheckpoint(stage=stage, dedupe_key=dedupe_key, status="SUCCEEDED", attempt=0, output_artifact_ids=tuple(outputs), owner=owner)
        existing_raw = self.redis.hget(self._stages_key(job_id), stage)
        if existing_raw:
            existing = self._checkpoint_from_raw(existing_raw)
            checkpoint = StageCheckpoint(
                stage=stage,
                dedupe_key=dedupe_key,
                status="SUCCEEDED",
                attempt=existing.attempt,
                output_artifact_ids=tuple(outputs),
                owner=owner,
            )
        checkpoint_json = _canonical_json({**checkpoint.__dict__, "output_artifact_ids": list(checkpoint.output_artifact_ids)})
        script_revision, storyboard_revision = _snapshot_meta(candidate)
        keys = [
            self._job_key(job_id),
            self._lease_key(job_id, stage),
            self._stages_key(job_id),
            self._cleanup_due_key,
            self._providers_key(job_id),
            self._provider_due_key,
            self._scripts_key(job_id),
            self._storyboards_key(job_id),
            self._artifacts_key(job_id),
        ]
        result = self._eval(
            _STAGE_COMPLETE_LUA,
            keys,
            [
                _snapshot_json(candidate),
                current.version,
                candidate.version,
                stage,
                dedupe_key,
                owner,
                checkpoint_json,
                job_expiry,
                job_id,
                script_revision,
                storyboard_revision,
                _canonical_json({"owner": owner, "dedupe_key": dedupe_key, "attempt": int(checkpoint.attempt)}),
            ],
        )
        status = self._status(result)
        if status == "GONE":
            raise JobGoneError()
        if status == "NOOP":
            return self._checkpoint_from_raw(self._result_value(result))
        if status in {"CONFLICT", "LEASE_LOST", "STALE", "STAGE_GONE"}:
            raise StateConflictError("stage lease or checkpoint fence rejected completion")
        if status != "OK":
            raise ReplicationError("STORE_ERROR", "stage completion failed")
        return checkpoint

    @staticmethod
    def _checkpoint_from_raw(raw: Any) -> StageCheckpoint:
        value = _json_load(raw)
        value["output_artifact_ids"] = tuple(value.get("output_artifact_ids", ()))
        return StageCheckpoint(**value)
