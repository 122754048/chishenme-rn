from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from redis.exceptions import ResponseError

from .errors import IdempotencyConflictError, ReplicationError
from .job_models import WorkMessage


_STAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FORBIDDEN_KEY_CHARS = frozenset("*?[]{}\x00\r\n\t")
_ALLOWED_FIELDS = frozenset({"job_id", "stage", "expected_version", "dedupe_key"})
_MAX_SAFE_INTEGER = 2**53


@dataclass(frozen=True)
class WorkDelivery:
    message_id: str
    message: WorkMessage


def _text(value: Any, *, field: str) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReplicationError("INVALID_INPUT", f"{field} must be valid UTF-8") from exc
    if not isinstance(value, str) or not value:
        raise ReplicationError("INVALID_INPUT", f"{field} must be a non-empty string")
    return value


def _key_component(value: Any, *, field: str) -> str:
    value = _text(value, field=field)
    if any(ord(char) < 32 or char.isspace() or char in _FORBIDDEN_KEY_CHARS for char in value):
        raise ReplicationError("INVALID_INPUT", f"{field} contains unsafe key characters")
    return value


def _stage(value: Any) -> str:
    value = _text(value, field="stage")
    if _STAGE_RE.fullmatch(value) is None:
        raise ReplicationError("INVALID_INPUT", "stage must be a safe key component")
    return value


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReplicationError("INVALID_INPUT", f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplicationError("INVALID_INPUT", f"{field} must be a non-negative integer")
    return value


def _safe_timestamp(value: Any, *, field: str) -> int:
    value = _nonnegative_int(value, field=field)
    if value > _MAX_SAFE_INTEGER:
        raise ReplicationError("INVALID_INPUT", f"{field} must be between 0 and 2**53")
    return value


def _message_values(message: WorkMessage) -> tuple[str, str, str, str]:
    return (message.job_id, message.stage, str(message.expected_version), message.dedupe_key)


def _decode_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _decode_xread(response: Any) -> list[tuple[str, Mapping[Any, Any]]]:
    """Normalize redis-py/fakeredis stream response tuples."""

    result: list[tuple[str, Mapping[Any, Any]]] = []
    if not response:
        return result
    if isinstance(response, Mapping):
        response = response.items()
    for stream_item in response:
        if isinstance(stream_item, Mapping):
            entries = stream_item.get(b"entries") or stream_item.get("entries") or stream_item.get(b"data") or stream_item.get("data") or ()
        else:
            try:
                entries = stream_item[1]
            except (IndexError, KeyError, TypeError) as exc:
                raise ReplicationError("QUEUE_CORRUPT", "Redis returned an invalid stream response") from exc
        for entry in entries or ():
            try:
                message_id, fields = entry[0], entry[1]
            except (IndexError, KeyError, TypeError) as exc:
                raise ReplicationError("QUEUE_CORRUPT", "Redis returned an invalid stream entry") from exc
            if not isinstance(fields, Mapping):
                if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes, bytearray)) and len(fields) % 2 == 0:
                    fields = {fields[index]: fields[index + 1] for index in range(0, len(fields), 2)}
                else:
                    raise ReplicationError("QUEUE_CORRUPT", "Redis returned invalid stream fields")
            result.append((_decode_text(message_id), fields))
    return result


def _decode_delivery(message_id: Any, fields: Mapping[Any, Any]) -> WorkDelivery:
    try:
        normalized = {_decode_text(key): _decode_text(value) for key, value in fields.items()}
    except (AttributeError, UnicodeDecodeError, TypeError) as exc:
        raise ReplicationError("QUEUE_CORRUPT", "stream entry fields are invalid") from exc
    if set(normalized) != _ALLOWED_FIELDS:
        raise ReplicationError("QUEUE_CORRUPT", "stream entry contains unexpected fields")
    job_id = normalized["job_id"]
    stage = normalized["stage"]
    dedupe_key = normalized["dedupe_key"]
    try:
        expected_version = int(normalized["expected_version"])
    except (TypeError, ValueError) as exc:
        raise ReplicationError("QUEUE_CORRUPT", "stream entry expected_version is invalid") from exc
    if normalized["expected_version"] != str(expected_version):
        raise ReplicationError("QUEUE_CORRUPT", "stream entry expected_version is not canonical")
    try:
        job_id = _key_component(job_id, field="job_id")
        stage = _stage(stage)
        dedupe_key = _key_component(dedupe_key, field="dedupe_key")
        expected_version = _positive_int(expected_version, field="expected_version")
    except ReplicationError as exc:
        raise ReplicationError("QUEUE_CORRUPT", "stream entry contains invalid message values") from exc
    return WorkDelivery(
        message_id=_decode_text(message_id),
        message=WorkMessage(job_id=job_id, stage=stage, expected_version=expected_version, dedupe_key=dedupe_key),
    )


_ENTRY_MATCH_LUA = r"""
local function entry_match(stream_key, message_id, job_id, stage, expected_version, dedupe_key)
    local rows = redis.call('XRANGE', stream_key, message_id, message_id)
    if #rows == 0 then
        return -2
    end
    local values = rows[1][2]
    if not values or #values ~= 8 then
        return -1
    end
    local fields = {}
    for index = 1, #values, 2 do
        local key = values[index]
        if key ~= 'job_id' and key ~= 'stage' and key ~= 'expected_version' and key ~= 'dedupe_key' then
            return -1
        end
        if fields[key] ~= nil then
            return -1
        end
        fields[key] = values[index + 1]
    end
    if fields.job_id == nil or fields.stage == nil or fields.expected_version == nil or fields.dedupe_key == nil then
        return -1
    end
    if fields.job_id == job_id and fields.stage == stage and
       fields.expected_version == expected_version and fields.dedupe_key == dedupe_key then
        return 1
    end
    return 0
end
"""


_XADD_HELPER_LUA = r"""
local function normalize_decimal(value)
    if not value or not string.match(value, '^%d+$') then
        return nil
    end
    local first = 1
    while first < #value and string.sub(value, first, first) == '0' do
        first = first + 1
    end
    return string.sub(value, first)
end

local function decimal_compare(left, right)
    left = normalize_decimal(left)
    right = normalize_decimal(right)
    if not left or not right then
        return nil
    end
    if #left < #right then
        return -1
    elseif #left > #right then
        return 1
    elseif left < right then
        return -1
    elseif left > right then
        return 1
    end
    return 0
end

local function decimal_increment(value)
    local digits = {}
    local carry = 1
    for index = #value, 1, -1 do
        local digit = string.byte(value, index) - 48 + carry
        if digit >= 10 then
            digit = digit - 10
            carry = 1
        else
            carry = 0
        end
        digits[index] = string.char(48 + digit)
    end
    if carry == 1 then
        table.insert(digits, 1, '1')
    end
    return table.concat(digits)
end

local function stream_id_parts(value)
    local dash = string.find(value, '-', 1, true)
    if not dash then
        return nil, nil
    end
    return normalize_decimal(string.sub(value, 1, dash - 1)), normalize_decimal(string.sub(value, dash + 1))
end

local function add_message(stream_key, last_id_key, job_id, stage, expected_version, dedupe_key)
    local previous = redis.call('GET', last_id_key)
    local message_id = redis.call('XADD', stream_key, '*',
        'job_id', job_id,
        'stage', stage,
        'expected_version', expected_version,
        'dedupe_key', dedupe_key)
    if previous then
        local previous_ms, previous_seq = stream_id_parts(previous)
        local current_ms, current_seq = stream_id_parts(message_id)
        local ms_order = decimal_compare(current_ms, previous_ms)
        local seq_order = decimal_compare(current_seq, previous_seq)
        if ms_order and seq_order and (ms_order < 0 or (ms_order == 0 and seq_order <= 0)) then
                redis.call('XDEL', stream_key, message_id)
                message_id = previous_ms .. '-' .. decimal_increment(previous_seq)
                message_id = redis.call('XADD', stream_key, message_id,
                    'job_id', job_id,
                    'stage', stage,
                    'expected_version', expected_version,
                    'dedupe_key', dedupe_key)
        end
    end
    redis.call('SET', last_id_key, message_id)
    return message_id
end
"""


_ENQUEUE_LUA = _ENTRY_MATCH_LUA + _XADD_HELPER_LUA + r"""
local existing = redis.call('HGET', KEYS[2], ARGV[4])
if existing then
    local match = entry_match(KEYS[1], existing, ARGV[1], ARGV[2], ARGV[3], ARGV[4])
    if match == 1 then
        return {'OK', existing}
    elseif match == 0 then
        return {'CONFLICT', existing}
    elseif match == -1 then
        return {'CONFLICT', existing}
    end
    if redis.call('HGET', KEYS[3], existing) == ARGV[4] then
        redis.call('HDEL', KEYS[3], existing)
    end
    if redis.call('HGET', KEYS[2], ARGV[4]) == existing then
        redis.call('HDEL', KEYS[2], ARGV[4])
    end
end
local message_id = add_message(KEYS[1], KEYS[4], ARGV[1], ARGV[2], ARGV[3], ARGV[4])
redis.call('HSET', KEYS[2], ARGV[4], message_id)
redis.call('HSET', KEYS[3], message_id, ARGV[4])
return {'NEW', message_id}
"""


_ACK_LUA = r"""
local function safe_component(value)
    if not value or value == '' then
        return false
    end
    for index = 1, string.len(value) do
        local byte = string.byte(value, index)
        local char = string.sub(value, index, index)
        if byte < 32 or string.match(char, '%s') or
           char == '*' or char == '?' or char == '[' or char == ']' or
           char == '{' or char == '}' then
            return false
        end
    end
    return true
end

local function safe_stage(value)
    return value and string.len(value) >= 1 and string.len(value) <= 128 and
           string.match(value, '^[A-Za-z0-9][A-Za-z0-9._-]*$') ~= nil
end

local old_reverse = redis.call('HGET', KEYS[3], ARGV[2])
local rows = redis.call('XRANGE', KEYS[1], ARGV[2], ARGV[2])
local dedupe_key = nil
local stream_present = (#rows > 0)
if stream_present then
    local values = rows[1][2]
    if not values or #values ~= 8 then
        return {'CORRUPT'}
    end
    local fields = {}
    for index = 1, #values, 2 do
        local key = values[index]
        if key ~= 'job_id' and key ~= 'stage' and key ~= 'expected_version' and key ~= 'dedupe_key' then
            return {'CORRUPT'}
        end
        if fields[key] ~= nil then
            return {'CORRUPT'}
        end
        fields[key] = values[index + 1]
    end
    if not safe_component(fields.job_id) or not safe_stage(fields.stage) or
       fields.expected_version == nil or not safe_component(fields.dedupe_key) or
       not string.match(fields.expected_version, '^%d+$') or
       (string.len(fields.expected_version) > 1 and string.sub(fields.expected_version, 1, 1) == '0') or
       fields.expected_version == '0' then
        return {'CORRUPT'}
    end
    dedupe_key = fields.dedupe_key
else
    dedupe_key = redis.call('HGET', KEYS[3], ARGV[2])
    if not dedupe_key then
        return {'NOOP'}
    end
end
local acknowledged = redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
if acknowledged ~= 1 then
    return {'NOOP'}
end
redis.call('XDEL', KEYS[1], ARGV[2])
if redis.call('HGET', KEYS[2], dedupe_key) == ARGV[2] then
    redis.call('HDEL', KEYS[2], dedupe_key)
end
if old_reverse and old_reverse ~= dedupe_key and redis.call('HGET', KEYS[2], old_reverse) == ARGV[2] then
    redis.call('HDEL', KEYS[2], old_reverse)
end
redis.call('HDEL', KEYS[3], ARGV[2])
return {'ACKED'}
"""


_SCHEDULE_LUA = r"""
local member = ARGV[4]
local job_field = '@job:' .. member
local stage_field = '@stage:' .. member
local version_field = '@version:' .. member
local due_field = '@due:' .. member
local existing_job = redis.call('HGET', KEYS[2], job_field)
local existing_stage = redis.call('HGET', KEYS[2], stage_field)
local existing_version = redis.call('HGET', KEYS[2], version_field)
local existing_due = redis.call('HGET', KEYS[2], due_field)
local existing_score = redis.call('ZSCORE', KEYS[1], member)
local complete = existing_score and existing_job and existing_job ~= '' and existing_stage and existing_stage ~= '' and
                 existing_version and existing_version ~= '' and existing_due and existing_due ~= ''
if complete then
    if existing_job == ARGV[1] and existing_stage == ARGV[2] and
       existing_version == ARGV[3] and existing_due == ARGV[5] and
       tonumber(existing_score) == tonumber(ARGV[5]) then
        return {'NOOP'}
    end
    return {'CONFLICT'}
end
if existing_score or existing_job or existing_stage or existing_version or existing_due then
    redis.call('ZREM', KEYS[1], member)
    redis.call('HDEL', KEYS[2], job_field, stage_field, version_field, due_field)
end
redis.call('HSET', KEYS[2],
    job_field, ARGV[1],
    stage_field, ARGV[2],
    version_field, ARGV[3],
    due_field, ARGV[5])
redis.call('ZADD', KEYS[1], ARGV[5], member)
return {'OK'}
"""


_PROMOTE_LUA = _ENTRY_MATCH_LUA + _XADD_HELPER_LUA + r"""
local function cleanup(member)
    redis.call('ZREM', KEYS[2], member)
    redis.call('HDEL', KEYS[3], '@job:' .. member, '@stage:' .. member, '@version:' .. member, '@due:' .. member)
end

local function canonical_decimal(value, allow_zero)
    if not value or not string.match(value, '^%d+$') then
        return false
    end
    if #value > 1 and string.sub(value, 1, 1) == '0' then
        return false
    end
    if not allow_zero and value == '0' then
        return false
    end
    return true
end

local members = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', ARGV[1], 'LIMIT', '0', ARGV[2])
local states = {}

-- Preflight every selected member before mutating any queue key. Redis Lua
-- does not roll back an earlier XADD when a later conflict is returned.
for index, member in ipairs(members) do
    local job_id = redis.call('HGET', KEYS[3], '@job:' .. member)
    local stage = redis.call('HGET', KEYS[3], '@stage:' .. member)
    local expected_version = redis.call('HGET', KEYS[3], '@version:' .. member)
    local due_at = redis.call('HGET', KEYS[3], '@due:' .. member)
    if not job_id or not stage or not expected_version or not due_at or job_id == '' or stage == '' then
        return {'CORRUPT', member}
    end
    if not canonical_decimal(expected_version, false) or not canonical_decimal(due_at, true) then
        return {'CORRUPT', member}
    end
    if decimal_compare(due_at, '9007199254740992') > 0 then
        return {'CORRUPT', member}
    end
    local score = redis.call('ZSCORE', KEYS[2], member)
    if not score or tonumber(score) ~= tonumber(due_at) then
        return {'CORRUPT', member}
    end
    local active_id = redis.call('HGET', KEYS[4], member)
    if active_id then
        local match = entry_match(KEYS[1], active_id, job_id, stage, expected_version, member)
        if match == 0 then
            return {'CONFLICT', member}
        elseif match == -1 then
            return {'CORRUPT', member}
        elseif match == 1 then
            states[index] = {kind = 'reuse', id = active_id}
        else
            states[index] = {kind = 'new', stale = active_id}
        end
    else
        states[index] = {kind = 'new', stale = ''}
    end
end

local result = {'OK'}
for index, member in ipairs(members) do
    local state = states[index]
    local job_id = redis.call('HGET', KEYS[3], '@job:' .. member)
    local stage = redis.call('HGET', KEYS[3], '@stage:' .. member)
    local expected_version = redis.call('HGET', KEYS[3], '@version:' .. member)
    if state.kind == 'reuse' then
        redis.call('HSET', KEYS[5], state.id, member)
        cleanup(member)
        table.insert(result, state.id)
    else
        if state.stale and state.stale ~= '' then
            if redis.call('HGET', KEYS[5], state.stale) == member then
                redis.call('HDEL', KEYS[5], state.stale)
            end
            if redis.call('HGET', KEYS[4], member) == state.stale then
                redis.call('HDEL', KEYS[4], member)
            end
        end
        local message_id = add_message(KEYS[1], KEYS[6], job_id, stage, expected_version, member)
        redis.call('HSET', KEYS[4], member, message_id)
        redis.call('HSET', KEYS[5], message_id, member)
        cleanup(member)
        table.insert(result, message_id)
    end
end
return result
"""


class RedisWorkQueue:
    """Short-lived Redis Streams work queue for stateless workers.

    Redis Standalone is the supported topology. Entries intentionally contain
    only the four fields represented by :class:`WorkMessage`.
    """

    def __init__(self, redis_client: Any, *, prefix: str = "usfr", group: str = "usfr-workers") -> None:
        self.redis = redis_client
        self.prefix = _key_component(prefix, field="prefix")
        self.group = _key_component(group, field="group")
        self.stream_key = f"{self.prefix}:work"
        self.scheduled_key = f"{self.prefix}:scheduled"
        self.active_dedupe_key = f"{self.prefix}:work:dedupe"
        self.message_dedupe_key = f"{self.prefix}:work:message-dedupe"
        self.last_id_key = f"{self.prefix}:work:last-id"
        self.scheduled_data_key = f"{self.prefix}:scheduled:data"
        try:
            self.redis.xgroup_create(self.stream_key, self.group, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc).upper():
                raise

    def enqueue(self, *, job_id: str, stage: str, expected_version: int, dedupe_key: str) -> str:
        message = self._validate_message(job_id=job_id, stage=stage, expected_version=expected_version, dedupe_key=dedupe_key)
        result = self.redis.eval(
            _ENQUEUE_LUA,
            4,
            self.stream_key,
            self.active_dedupe_key,
            self.message_dedupe_key,
            self.last_id_key,
            *(_message_values(message)),
        )
        status = _decode_text(result[0]) if result else ""
        if status == "CONFLICT":
            raise IdempotencyConflictError(dedupe_key=message.dedupe_key)
        if status not in {"NEW", "OK"} or len(result) < 2:
            raise ReplicationError("QUEUE_ERROR", "unable to enqueue work")
        return _decode_text(result[1])

    def read(self, *, consumer: str, count: int = 1, block_ms: int = 0) -> tuple[WorkDelivery, ...]:
        consumer = _key_component(consumer, field="consumer")
        count = _positive_int(count, field="count")
        block_ms = _nonnegative_int(block_ms, field="block_ms")
        # A zero timeout is the public non-blocking default. Redis uses None
        # for an immediate XREADGROUP call; BLOCK 0 would wait forever.
        response = self.redis.xreadgroup(
            self.group,
            consumer,
            {self.stream_key: ">"},
            count=count,
            block=block_ms if block_ms > 0 else None,
        )
        return tuple(_decode_delivery(message_id, fields) for message_id, fields in _decode_xread(response))

    def ack(self, message_id: str) -> bool:
        message_id = _key_component(message_id, field="message_id")
        result = self.redis.eval(
            _ACK_LUA,
            3,
            self.stream_key,
            self.active_dedupe_key,
            self.message_dedupe_key,
            self.group,
            message_id,
        )
        status = _decode_text(result[0]) if result else "NOOP"
        if status == "CORRUPT":
            raise ReplicationError("QUEUE_CORRUPT", "stream entry is malformed")
        return status == "ACKED"

    def reclaim(self, *, consumer: str, min_idle_ms: int, count: int = 10) -> tuple[WorkDelivery, ...]:
        consumer = _key_component(consumer, field="consumer")
        min_idle_ms = _nonnegative_int(min_idle_ms, field="min_idle_ms")
        count = _positive_int(count, field="count")
        response = self.redis.xautoclaim(
            self.stream_key,
            self.group,
            consumer,
            min_idle_ms,
            start_id="0-0",
            count=count,
            justid=False,
        )
        entries = self._xautoclaim_entries(response)
        return tuple(_decode_delivery(message_id, fields) for message_id, fields in entries)

    def schedule(
        self,
        *,
        job_id: str,
        stage: str,
        expected_version: int,
        dedupe_key: str,
        due_at_ms: int,
    ) -> bool:
        message = self._validate_message(job_id=job_id, stage=stage, expected_version=expected_version, dedupe_key=dedupe_key)
        due_at_ms = _safe_timestamp(due_at_ms, field="due_at_ms")
        result = self.redis.eval(
            _SCHEDULE_LUA,
            2,
            self.scheduled_key,
            self.scheduled_data_key,
            message.job_id,
            message.stage,
            str(message.expected_version),
            message.dedupe_key,
            str(due_at_ms),
        )
        status = _decode_text(result[0]) if result else ""
        if status == "CONFLICT":
            raise IdempotencyConflictError(dedupe_key=message.dedupe_key)
        if status not in {"OK", "NOOP"}:
            raise ReplicationError("QUEUE_ERROR", "unable to schedule work")
        return status == "OK"

    def promote_due(self, *, now_ms: int, limit: int = 100) -> tuple[str, ...]:
        now_ms = _safe_timestamp(now_ms, field="now_ms")
        limit = _positive_int(limit, field="limit")
        result = self.redis.eval(
            _PROMOTE_LUA,
            6,
            self.stream_key,
            self.scheduled_key,
            self.scheduled_data_key,
            self.active_dedupe_key,
            self.message_dedupe_key,
            self.last_id_key,
            str(now_ms),
            str(limit),
        )
        if not result:
            raise ReplicationError("QUEUE_ERROR", "unable to promote scheduled work")
        status = _decode_text(result[0])
        if status == "CONFLICT":
            dedupe_key = _decode_text(result[1]) if len(result) > 1 else ""
            raise IdempotencyConflictError(dedupe_key=dedupe_key)
        if status == "CORRUPT":
            raise ReplicationError("QUEUE_CORRUPT", "scheduled sidecar is malformed")
        if status != "OK":
            raise ReplicationError("QUEUE_ERROR", "unable to promote scheduled work")
        return tuple(_decode_text(message_id) for message_id in result[1:])

    def pending_count(self) -> int:
        try:
            response = self.redis.xpending(self.stream_key, self.group)
        except ResponseError as exc:
            if "NOGROUP" in str(exc).upper():
                return 0
            raise
        if isinstance(response, Mapping):
            value = response.get("pending", response.get(b"pending", 0))
            return int(value or 0)
        if isinstance(response, Sequence) and not isinstance(response, (str, bytes, bytearray)):
            return int(response[0] or 0) if response else 0
        return int(response or 0)

    @staticmethod
    def _validate_message(*, job_id: str, stage: str, expected_version: int, dedupe_key: str) -> WorkMessage:
        return WorkMessage(
            job_id=_key_component(job_id, field="job_id"),
            stage=_stage(stage),
            expected_version=_positive_int(expected_version, field="expected_version"),
            dedupe_key=_key_component(dedupe_key, field="dedupe_key"),
        )

    @staticmethod
    def _xautoclaim_entries(response: Any) -> list[tuple[Any, Mapping[Any, Any]]]:
        if not response:
            return []
        if isinstance(response, Mapping):
            entries = response.get("entries") or response.get(b"entries") or response.get("messages") or response.get(b"messages") or ()
        else:
            try:
                entries = response[1]
            except (IndexError, KeyError, TypeError) as exc:
                raise ReplicationError("QUEUE_CORRUPT", "Redis returned an invalid XAUTOCLAIM response") from exc
        normalized: list[tuple[Any, Mapping[Any, Any]]] = []
        if isinstance(entries, Mapping):
            entries = entries.items()
        for entry in entries or ():
            try:
                message_id, fields = entry[0], entry[1]
            except (IndexError, KeyError, TypeError) as exc:
                raise ReplicationError("QUEUE_CORRUPT", "Redis returned an invalid XAUTOCLAIM entry") from exc
            if isinstance(fields, Mapping):
                normalized.append((message_id, fields))
                continue
            if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes, bytearray)) and len(fields) % 2 == 0:
                normalized.append((message_id, {fields[index]: fields[index + 1] for index in range(0, len(fields), 2)}))
                continue
            raise ReplicationError("QUEUE_CORRUPT", "Redis returned invalid XAUTOCLAIM fields")
        return normalized


__all__ = ["RedisWorkQueue", "WorkDelivery"]
