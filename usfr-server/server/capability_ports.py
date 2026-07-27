"""Runtime bindings for the seven production high-fidelity capabilities.

The stage-capability manifest is deployment metadata only.  This module binds
that metadata to executable, server-injected adapters and rejects a complete
manifest when the corresponding port is missing, has the wrong interface, or
reports a different implementation digest.  It intentionally does not ship
placeholder visual/audio/provider implementations: dynamics, ASR/OCR, and
provider adapters remain real deployment dependencies, while the packaged
Seedance compiler and deterministic compositor/QC can be wrapped here.

No RunState stage is added.  ``CapabilityStagePort`` is a thin adapter used by
existing stage names, and ``validate_*`` functions are startup/invocation
guards that preserve the legacy development path when the profile is inactive.
"""

from __future__ import annotations

import inspect
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .capabilities import REQUIRED_CAPABILITIES, validate_stage_capability_manifest
from .performance_audio_contracts import build_audio_evidence_contracts
from .source_content_timeline import SourceContentTimelineError, build_source_content_timeline


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# These are the smallest callable contracts.  A deployment adapter may expose
# additional methods, but it may not merely declare a capability without the
# method that the canonical workflow actually invokes.
REQUIRED_CAPABILITY_METHODS: dict[str, tuple[str, ...]] = {
    "dynamics_analyzer": ("analyze",),
    "asr_transcriber": ("transcribe",),
    "ocr_ui_renderer": ("render_and_verify",),
    "seedance20_compiler": ("invoke_a", "invoke_b"),
    "compositor": ("compose",),
    "qc_engine": ("run",),
    "provider_adapter": ("create_asset", "create_video", "lookup"),
}


# Stage names remain the existing twelve-stage plan.  ``analyze_dynamics``
# owns the paired audio transcription call; it is not a new ASR stage.
STAGE_CAPABILITY_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "analyze_dynamics": ("dynamics_analyzer", "asr_transcriber"),
    "resolve_ui_evidence": ("ocr_ui_renderer",),
    "build_script": ("seedance20_compiler",),
    "compile_seedance20_prompt": ("seedance20_compiler",),
    "audit_seedance_request": ("seedance20_compiler",),
    "splice_timeline": ("compositor",),
    "run_qc": ("qc_engine",),
}
_DIRECT_CAPABILITY_STAGES = frozenset({
    "analyze_dynamics",
    "resolve_ui_evidence",
    "splice_timeline",
    "run_qc",
})
_COMPOSITE_CAPABILITY_STAGES = frozenset({
    "build_script",
    "compile_seedance20_prompt",
    "audit_seedance_request",
})


class BoundRuntimeCapability:
    """Attach immutable deployment identity to a real injected adapter.

    The wrapper delegates methods to ``adapter``; it never synthesizes output
    or supplies a no-op fallback.  It is useful for packaged implementations
    such as ``SeedanceInvocationAdapter`` and for vendor clients whose classes
    do not natively expose manifest identity fields.
    """

    def __init__(
        self,
        *,
        capability: str,
        implementation: str,
        version: str,
        sha256: str,
        adapter: Any,
    ) -> None:
        if capability not in REQUIRED_CAPABILITY_METHODS:
            raise ValueError(f"unsupported runtime capability: {capability}")
        if adapter is None:
            raise ValueError(f"{capability} requires a real adapter")
        self.capability = capability
        self.implementation = str(implementation)
        self.version = str(version)
        self.sha256 = str(sha256)
        self.adapter = adapter
        _validate_methods(self, capability)

    def capability_identity(self) -> dict[str, str]:
        identity = {
            "capability": self.capability,
            "implementation": self.implementation,
            "version": self.version,
            "sha256": self.sha256,
        }
        # A wrapper is often the manifest-facing port for a concrete adapter.
        # If that adapter exposes a composite identity (for example, a model,
        # renderer, or compositor dependency digest), preserve it instead of
        # silently reverting to the wrapper's hand-entered outer SHA.  Older
        # test/dev adapters do not expose this method and retain the historical
        # identity exactly.
        nested_identity = getattr(self.adapter, "capability_identity", None)
        if callable(nested_identity):
            nested = nested_identity()
            if isinstance(nested, Mapping):
                nested_sha = nested.get("sha256")
                if nested_sha is not None and str(nested_sha) != self.sha256:
                    nested_sha_text = str(nested_sha)
                    if _SHA256.fullmatch(nested_sha_text) is None:
                        raise ValueError(
                            f"{self.capability} nested capability identity sha256 must be lowercase SHA-256"
                        )
                    identity["sha256"] = nested_sha_text
        return identity

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)


def _identity(adapter: Any, name: str) -> Mapping[str, Any]:
    """Read the immutable deployment identity exposed by a port.

    Ports may implement ``capability_identity()`` or expose the four fields as
    attributes.  No identity is inferred from a Python module path, class
    name, or a local Skill checkout; missing identity is a deployment error.
    """

    value = getattr(adapter, "capability_identity", None)
    if callable(value):
        value = value()
    if value is None:
        value = {
            "capability": getattr(adapter, "capability", None),
            "implementation": getattr(adapter, "implementation", None),
            "version": getattr(adapter, "version", None),
            "sha256": getattr(adapter, "sha256", None),
        }
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} capability identity must be an object")
    missing = [field for field in ("implementation", "version", "sha256") if not value.get(field)]
    if missing:
        raise ValueError(f"{name} capability identity missing: {', '.join(missing)}")
    declared_name = value.get("capability")
    if declared_name is not None and str(declared_name) != name:
        raise ValueError(f"{name} capability identity names {declared_name!r}")
    return value


def _validate_methods(adapter: Any, name: str) -> None:
    for method_name in REQUIRED_CAPABILITY_METHODS[name]:
        method = getattr(adapter, method_name, None)
        if not callable(method):
            raise ValueError(f"{name} capability port must implement {method_name}()")


def validate_runtime_capability_ports(
    capability_ports: Mapping[str, Any] | None,
    *,
    manifest: Mapping[str, Any] | None,
    production: bool,
    profile_active: bool,
) -> dict[str, Any]:
    """Bind a production manifest to executable capability ports.

    ``None``/empty ports remain valid only for legacy or local development.
    Active production profiles require exactly the seven fixed capabilities,
    callable methods, and an adapter identity that matches the manifest's
    implementation/version/SHA-256 byte record.  This check is deliberately
    stronger than ``validate_stage_capability_manifest`` and prevents an
    operator from passing a hand-written sidecar with no real worker behind it.
    """

    if not production or not profile_active:
        return dict(capability_ports or {})
    validate_stage_capability_manifest(manifest, production=True, profile_active=True)
    if not isinstance(capability_ports, Mapping) or not capability_ports:
        raise ValueError("active production profile requires runtime capability ports")
    unknown = sorted(set(str(name) for name in capability_ports) - set(REQUIRED_CAPABILITIES))
    if unknown:
        raise ValueError(f"runtime capability ports contain unsupported capabilities: {', '.join(unknown)}")
    missing = [name for name in REQUIRED_CAPABILITIES if name not in capability_ports]
    if missing:
        raise ValueError(f"runtime capability ports missing required capabilities: {', '.join(missing)}")
    records = manifest.get("capabilities") if isinstance(manifest, Mapping) else None
    if not isinstance(records, Mapping):  # defensive; manifest validator already checks this
        raise ValueError("stage capability manifest capabilities must be an object")
    bound: dict[str, Any] = {}
    for name in REQUIRED_CAPABILITIES:
        adapter = capability_ports.get(name)
        if adapter is None:
            raise ValueError(f"runtime capability ports missing required capabilities: {name}")
        identity = _identity(adapter, name)
        _validate_methods(adapter, name)
        if name == "ocr_ui_renderer":
            # The packaged DeterministicUiRenderer deliberately keeps its
            # PNG normalizer for local/legacy compatibility.  In an active
            # production profile it must be backed by a real multi-state
            # video renderer; otherwise generated_ui_demo would fail only
            # after a worker lease was claimed.
            concrete = getattr(adapter, "adapter", adapter)
            readiness = getattr(concrete, "validate_production_readiness", None)
            if callable(readiness):
                readiness()
        expected = records.get(name)
        if not isinstance(expected, Mapping):
            raise ValueError(f"{name} capability manifest record must be an object")
        for field in ("implementation", "version", "sha256"):
            if str(identity.get(field)) != str(expected.get(field)):
                raise ValueError(f"{name} capability {field} does not match manifest")
        bound[name] = adapter
    return bound


def validate_provider_callable_binding(
    capability_ports: Mapping[str, Any] | None,
    operation: str,
    candidate: Any,
    *,
    manifest: Mapping[str, Any] | None = None,
    production: bool,
    profile_active: bool,
) -> Any:
    """Require a provider call to be a method of the validated adapter.

    The service still accepts the historical callable injection in local and
    legacy runs.  An active production profile has a stronger boundary: a
    lambda, partial, or unrelated client cannot be passed around the durable
    intent gate.  The candidate must be the exact bound method exposed by the
    manifest-matched ``provider_adapter`` instance.  Returning the candidate
    keeps this helper convenient for router/worker call sites.
    """

    if not production or not profile_active:
        if not callable(candidate):
            raise ValueError(f"provider {operation} callable is required")
        return candidate
    if operation not in {"create_asset", "create_video", "lookup"}:
        raise ValueError(f"unsupported provider operation: {operation}")
    bound = validate_runtime_capability_ports(
        capability_ports,
        manifest=manifest,
        production=production,
        profile_active=profile_active,
    )

    adapter = bound.get("provider_adapter")
    expected = getattr(adapter, operation, None)
    if not callable(expected) or not callable(candidate):
        raise ValueError(f"provider_adapter.{operation} is not callable")

    expected_self = getattr(expected, "__self__", None)
    expected_func = getattr(expected, "__func__", None)
    candidate_self = getattr(candidate, "__self__", None)
    candidate_func = getattr(candidate, "__func__", None)
    if (
        expected_self is None
        or expected_func is None
        or candidate_self is not expected_self
        or candidate_func is not expected_func
    ):
        raise ValueError(
            f"provider {operation} callable must be bound to the validated provider_adapter"
        )
    return candidate


def _publish_internal_json_contract(
    *,
    context: Any,
    kind: str,
    value: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Publish a temporary immutable sidecar when the Worker owns storage.

    Local compatibility contexts intentionally retain their inline result
    behavior.  A deployed active profile cannot silently skip publication,
    because downstream stages receive durable artifacts rather than a mutable
    in-process stage-output cache.
    """

    publisher = getattr(context, "publish_bytes", None)
    raw = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    if callable(publisher):
        return publisher(
            kind=kind,
            data=raw,
            content_type="application/json",
            expected_sha256=digest,
        )
    if getattr(context, "allow_local_paths", True) is False:
        raise ValueError(f"{kind} requires the worker artifact publisher")
    return None


def _source_video_sha256(context: Any, dynamics: Mapping[str, Any]) -> str:
    """Resolve the one immutable source digest already admitted for this Job."""

    candidates: list[Any] = [
        dynamics.get("source_video_sha256"),
        dynamics.get("source_sha256"),
    ]
    evidence = dynamics.get("evidence")
    if isinstance(evidence, Mapping):
        probe = evidence.get("probe")
        if isinstance(probe, Mapping):
            candidates.append(probe.get("source_sha256"))
    snapshot = getattr(context, "snapshot", None)
    manifest = getattr(snapshot, "slots_manifest", None)
    if isinstance(manifest, Mapping):
        slots = manifest.get("slots")
        source_slot = slots.get("source_video") if isinstance(slots, Mapping) else None
        values = source_slot.get("sha256") if isinstance(source_slot, Mapping) else None
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)) and len(values) == 1:
            candidates.append(values[0])
    for candidate in candidates:
        value = str(candidate or "").strip().lower()
        if _SHA256.fullmatch(value) is not None:
            return value
    raise ValueError("analyze_dynamics requires exactly one immutable source_video SHA-256")


def _declared_capability_names(stage_port: Any) -> tuple[str, ...]:
    value = getattr(stage_port, "capability_names", None)
    if value is None:
        value = getattr(stage_port, "capability_name", None)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value)
    return ()


def validate_stage_port_bindings(
    stage_ports: Mapping[str, Any] | None,
    capability_ports: Mapping[str, Any] | None,
    *,
    manifest: Mapping[str, Any] | None,
    production: bool,
    profile_active: bool,
    invocation_adapter: Any | None = None,
) -> None:
    """Ensure injected StagePorts identify the capabilities they execute.

    Only handlers that are present are checked; route planning still decides
    which existing stages run.  A production handler for a capability-bearing
    stage must explicitly expose ``capability_name`` or ``capability_names``
    and the names must match the canonical map.  This prevents a generic
    callable returning a plausible sidecar from bypassing the bound port.
    """

    if not production or not profile_active:
        return None
    bound = validate_runtime_capability_ports(
        capability_ports,
        manifest=manifest,
        production=production,
        profile_active=profile_active,
    )
    if not isinstance(stage_ports, Mapping):
        raise ValueError("active production profile requires runtime StagePorts")
    for stage, required in STAGE_CAPABILITY_REQUIREMENTS.items():
        if stage not in stage_ports:
            continue
        stage_port = stage_ports[stage]
        declared = _declared_capability_names(stage_port)
        if set(declared) != set(required):
            raise ValueError(
                f"{stage} StagePort must declare capabilities {', '.join(required)}"
            )
        if any(name not in bound for name in required):
            raise ValueError(f"{stage} StagePort references an unbound capability")
        if stage in _DIRECT_CAPABILITY_STAGES:
            if not isinstance(stage_port, CapabilityStagePort):
                raise ValueError(f"{stage} must use CapabilityStagePort to execute its bound capability")
            for name in required:
                if stage_port._ports.get(name) is not bound[name]:
                    raise ValueError(f"{stage} CapabilityStagePort does not use the validated {name} adapter")
        elif stage in _COMPOSITE_CAPABILITY_STAGES and not isinstance(stage_port, BoundStagePort):
            raise ValueError(f"{stage} must use BoundStagePort with the existing canonical handler")
        elif stage in _COMPOSITE_CAPABILITY_STAGES:
            compiler = bound["seedance20_compiler"]
            if invocation_adapter is None:
                raise ValueError(f"{stage} requires the bound Seedance invocation adapter")
            underlying = getattr(compiler, "adapter", None)
            if invocation_adapter is not compiler and invocation_adapter is not underlying:
                raise ValueError(f"{stage} StagePort is not paired with the validated invocation adapter")
    return None


def _call(method: Any, *, context: Any, input_artifacts: list[Mapping[str, Any]], **extra: Any) -> Any:
    """Invoke a strict capability method while allowing narrow adapters.

    The canonical signature is keyword-only ``context`` and
    ``input_artifacts``.  The fallback forms support existing server ports
    without accepting workstation paths or silently swallowing implementation
    errors; signature binding happens before one invocation only.
    """

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(context=context, input_artifacts=input_artifacts, **extra)
    candidates = (
        {"context": context, "input_artifacts": input_artifacts, **extra},
        {"context": context, "input_artifacts": input_artifacts},
        {"context": context},
        {"input_artifacts": input_artifacts},
        {},
    )
    for kwargs in candidates:
        try:
            signature.bind(**kwargs)
        except TypeError:
            continue
        return method(**kwargs)
    for args in ((context, input_artifacts), (context,), ()):
        try:
            signature.bind(*args)
        except TypeError:
            continue
        return method(*args)
    raise ValueError("capability method signature must accept context/input_artifacts")


def _require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field} must be a non-empty object")
    return value


def _require_artifact(value: Any, field: str) -> Mapping[str, Any]:
    artifact = _require_object(value, field)
    reference = artifact.get("object_key") or artifact.get("uri")
    if not reference:
        raise ValueError(f"{field} requires an immutable object reference")
    reference_text = str(reference)
    folded_reference = reference_text.casefold()
    if (
        folded_reference.startswith(("file://", "local:", "path:", "~/.codex"))
        or reference_text.startswith(("/", "\\"))
        or (len(reference_text) > 1 and reference_text[1] == ":" and reference_text[0].isalpha())
    ):
        raise ValueError(f"{field} cannot use a local output reference")
    sha = artifact.get("sha256")
    if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
        raise ValueError(f"{field}.sha256 must be lowercase SHA-256")
    return artifact


def _require_result(value: Any, capability: str, *, operation: str | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{capability} capability returned no executable evidence")
    if capability == "dynamics_analyzer":
        analysis = _require_object(value.get("source_dynamics_analysis"), "source_dynamics_analysis")
        cuts = analysis.get("source_cuts", analysis.get("cuts"))
        if not isinstance(cuts, list) or not cuts:
            raise ValueError("source_dynamics_analysis.source_cuts must contain frame-zero-to-end Cut evidence")
    elif capability == "asr_transcriber":
        audio = _require_object(value.get("audio_contract"), "audio_contract")
        if not isinstance(audio.get("segments"), list):
            raise ValueError("audio_contract.segments must be an array")
        silence = audio.get("meaningful_silence", audio.get("silence_windows"))
        if not isinstance(silence, list):
            raise ValueError("audio_contract.meaningful_silence or silence_windows must be an array")
    elif capability == "ocr_ui_renderer":
        _require_object(value.get("ui_truth_card"), "ui_truth_card")
        _require_object(value.get("ui_render_contract"), "ui_render_contract")
        _require_artifact(value.get("rendered_media"), "rendered_media")
        if value.get("ocr_match_percent") != 100:
            raise ValueError("generated UI OCR match must equal 100")
        if value.get("layout_match_percent") != 100:
            raise ValueError("generated UI layout match must equal 100")
    elif capability == "seedance20_compiler":
        if operation == "build_script":
            if value.get("profile") != "seedance20_prescript_v1":
                raise ValueError("Invocation A must return a seedance20_prescript_v1 artifact")
        elif operation == "compile_seedance20_prompt":
            sha = value.get("compiled_prompt_sha256")
            if value.get("status") != "ready" or not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
                raise ValueError("Invocation B must return a ready compiled prompt SHA-256")
    elif capability == "compositor":
        _require_artifact(value.get("output_artifact"), "output_artifact")
        _require_object(value.get("timeline_manifest"), "timeline_manifest")
    elif capability == "qc_engine":
        _require_object(value.get("qc_report"), "qc_report")
        if value.get("passed") is not True:
            raise ValueError("QC engine must block delivery unless passed=true")
    return value


def _require_high_fidelity_dynamics_extension(value: Mapping[str, Any]) -> None:
    analysis = value.get("source_dynamics_analysis")
    extension = (
        (analysis.get("extensions") or {}).get("high_fidelity_hybrid_v1")
        if isinstance(analysis, Mapping)
        else None
    )
    if not isinstance(extension, Mapping):
        raise ValueError(
            "active high-fidelity dynamics requires extensions.high_fidelity_hybrid_v1"
        )
    # Presence alone is not evidence.  Validate the full packaged extension
    # contract at the stage boundary so a custom deployment adapter cannot
    # bypass the same scene/performance/action/audio coverage enforced by the
    # bundled FFmpeg/VLM adapter.
    try:
        import importlib.util
        from pathlib import Path

        validator_path = (
            Path(__file__).resolve().parents[1]
            / "bundled-skills"
            / "analyze-reference-video-dynamics"
            / "scripts"
            / "validate_high_fidelity_extension.py"
        )
        spec = importlib.util.spec_from_file_location(
            "usfr_stage_high_fidelity_extension_validator", validator_path
        )
        if spec is None or spec.loader is None:
            raise ValueError("packaged high-fidelity extension validator is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_high_fidelity_extension(dict(analysis))
    except Exception as exc:
        raise ValueError(
            f"active high-fidelity dynamics extension validation failed: {exc}"
        ) from exc


def _context_has_generated_ui(context: Any) -> bool:
    return any(
        str(item.get("region_type") or item.get("kind") or "").lower()
        in {"generated_ui_demo", "generated_ui"}
        for item in (getattr(context, "timeline_regions", ()) or ())
        if isinstance(item, Mapping)
    )


def _require_active_generated_ui_video(value: Mapping[str, Any]) -> None:
    media = value.get("rendered_media")
    truth = value.get("ui_truth_card")
    render_contract = value.get("ui_render_contract")
    report = value.get("ui_qc_report")
    media_metadata = media.get("metadata") if isinstance(media, Mapping) else None
    content_type = str(
        (media.get("content_type") if isinstance(media, Mapping) else None)
        or (media_metadata.get("content_type") if isinstance(media_metadata, Mapping) else None)
        or ""
    ).lower()
    media_kind = str(media.get("kind") or "") if isinstance(media, Mapping) else ""
    states = truth.get("states") if isinstance(truth, Mapping) else None
    state_ids = [str(item.get("state_id") or "") for item in states or [] if isinstance(item, Mapping)]
    evidence = report.get("state_evidence") if isinstance(report, Mapping) else None
    evidence_ids = [str(item.get("state_id") or "") for item in evidence or [] if isinstance(item, Mapping)]
    truth_basis = str(
        value.get("truth_basis")
        or (truth.get("truth_basis") if isinstance(truth, Mapping) else "")
        or (media_metadata.get("truth_basis") if isinstance(media_metadata, Mapping) else "")
        or ""
    ).strip().lower()
    truth_digest = str(
        value.get("ui_truth_card_sha256")
        or (report.get("ui_truth_card_sha256") if isinstance(report, Mapping) else "")
        or ""
    ).lower()
    truth_source_digest = str(
        value.get("truth_source_sha256")
        or (report.get("truth_source_sha256") if isinstance(report, Mapping) else "")
        or ""
    ).lower()
    def valid_sha(value: Any) -> bool:
        return isinstance(value, str) and _SHA256.fullmatch(value.lower()) is not None

    states_valid = (
        isinstance(states, list)
        and bool(states)
        and len(state_ids) == len(states)
        and all(state_ids)
        and len(state_ids) == len(set(state_ids))
        and all(
            isinstance(state, Mapping)
            and isinstance(state.get("frame_ms"), int)
            and not isinstance(state.get("frame_ms"), bool)
            and state.get("frame_ms") >= 0
            and isinstance(state.get("expected_text"), list)
            and all(isinstance(item, str) for item in state.get("expected_text") or [])
            and isinstance(state.get("expected_layout"), list)
            for state in states
        )
    )
    evidence_valid = False
    if isinstance(evidence, list) and evidence_ids == state_ids:
        evidence_valid = True
        for row in evidence:
            if not isinstance(row, Mapping):
                evidence_valid = False
                break
            frame_sha = row.get("decoded_frame_sha256") or row.get("frame_sha256")
            if not valid_sha(frame_sha) or not valid_sha(row.get("truth_state_sha256")):
                evidence_valid = False
                break
            for kind in ("ocr_evidence", "layout_evidence"):
                receipt = row.get(kind)
                if not isinstance(receipt, Mapping) or not valid_sha(receipt.get("input_sha256")):
                    evidence_valid = False
                    break
                if not isinstance(receipt.get("records"), list) or not valid_sha(receipt.get("records_sha256")):
                    evidence_valid = False
                    break
                decoded_sha = receipt.get("decoded_frame_sha256")
                if decoded_sha is not None and not valid_sha(decoded_sha):
                    evidence_valid = False
                    break
                if kind == "ocr_evidence":
                    if (
                        not valid_sha(receipt.get("request_sha256"))
                        or not valid_sha(receipt.get("response_sha256"))
                        or not valid_sha(receipt.get("model_sha256"))
                        or not str(receipt.get("model_id") or "").strip()
                    ):
                        evidence_valid = False
                        break
            if not evidence_valid:
                break
            if row.get("ocr_match_percent") != 100 or row.get("layout_match_percent") != 100:
                evidence_valid = False
                break
    animation_evidence = report.get("animation_interval_evidence") if isinstance(report, Mapping) else None
    animation_valid = isinstance(animation_evidence, list)
    if animation_valid:
        for interval in animation_evidence:
            if not isinstance(interval, Mapping):
                animation_valid = False
                break
            samples = interval.get("samples")
            if not isinstance(samples, list) or not samples:
                animation_valid = False
                break
            for sample in samples:
                if not isinstance(sample, Mapping) or not valid_sha(sample.get("decoded_frame_sha256") or sample.get("frame_sha256")):
                    animation_valid = False
                    break
                if sample.get("ocr_match_percent") != 100 or sample.get("layout_match_percent") != 100:
                    animation_valid = False
                    break
                for kind in ("ocr_evidence", "layout_evidence"):
                    receipt = sample.get(kind)
                    if (
                        not isinstance(receipt, Mapping)
                        or not valid_sha(receipt.get("input_sha256"))
                        or not isinstance(receipt.get("records"), list)
                        or not valid_sha(receipt.get("records_sha256"))
                    ):
                        animation_valid = False
                        break
                    decoded_sha = receipt.get("decoded_frame_sha256")
                    if decoded_sha is not None and not valid_sha(decoded_sha):
                        animation_valid = False
                        break
                    for record in receipt.get("records", []):
                        if not isinstance(record, Mapping):
                            animation_valid = False
                            break
                        text = str(record.get("text") or "")
                        if not text.strip() or any(char in text for char in ("\ufffd", "\u25a1")):
                            animation_valid = False
                            break
                        bbox = record.get("bbox")
                        if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes, bytearray)) or len(bbox) < 4:
                            animation_valid = False
                            break
                        try:
                            x1, y1, x2, y2 = [float(item) for item in bbox[:4]]
                        except (TypeError, ValueError):
                            animation_valid = False
                            break
                        if not (0 <= x1 < x2 and 0 <= y1 < y2):
                            animation_valid = False
                            break
                    if not animation_valid:
                        break
                if not animation_valid:
                    break
            if not animation_valid:
                break
    valid = (
        isinstance(media, Mapping)
        and media_kind == "generated_ui_video"
        and content_type.startswith("video/")
        and states_valid
        and isinstance(render_contract, Mapping)
        and render_contract.get("state_sequence") == state_ids
        and isinstance(report, Mapping)
        and evidence_valid
        and report.get("ocr_match_percent") == 100
        and report.get("layout_match_percent") == 100
        and truth_basis in {
            "target-owned-upload",
            "user-ui-screenshot",
            "parsed-app-store-evidence",
            "official-app-evidence",
        }
        and _SHA256.fullmatch(truth_digest) is not None
        and _canonical_sha256(truth) == truth_digest
        and _SHA256.fullmatch(truth_source_digest) is not None
        and animation_valid
        and report.get("animation_qc_required") is True
        and report.get("animation_ocr_match_percent") == 100
        and report.get("animation_layout_match_percent") == 100
    )
    if not valid:
        raise ValueError(
            "active generated UI requires immutable video media and complete frame-bound state_evidence; PNG/summary-only evidence is invalid"
        )


def _current_qc_media_authority(
    context: Any,
    input_artifacts: list[Mapping[str, Any]],
) -> tuple[str, set[str]]:
    """Resolve the current Run's final output and admissible source digests.

    The weighted report is supplied by a deployment-owned QC adapter, so its
    own ``media_bindings`` cannot be the authority for which bytes belong to
    this Run.  Active production derives that authority from the immutable
    WorkerStageContext descriptors already admitted by the server.
    """

    artifacts = [
        item
        for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping)
    ]
    final_output_sha256 = ""
    for kind in ("assembled_video", "provider_video"):
        for item in artifacts:
            if str(item.get("kind") or "") != kind:
                continue
            digest = str(item.get("sha256") or "")
            if _SHA256.fullmatch(digest) is not None:
                final_output_sha256 = digest
                break
        if final_output_sha256:
            break
    if not final_output_sha256:
        raise ValueError(
            "active high-fidelity QC cannot resolve the current final output artifact"
        )

    current_run_source_sha256s: set[str] = set()

    def add_digest(raw: Any) -> None:
        digest = str(raw or "")
        if _SHA256.fullmatch(digest) is not None:
            current_run_source_sha256s.add(digest)

    for slot in getattr(context, "input_slots", ()) or ():
        if not isinstance(slot, Mapping) or not slot.get("present"):
            continue
        digests = slot.get("sha256")
        if isinstance(digests, str):
            add_digest(digests)
        elif isinstance(digests, Sequence) and not isinstance(
            digests, (str, bytes, bytearray)
        ):
            for digest in digests:
                add_digest(digest)
    for item in input_artifacts or []:
        if isinstance(item, Mapping) and str(item.get("kind") or "") not in {
            "assembled_video",
            "provider_video",
            "high_fidelity_qc_extension",
        }:
            add_digest(item.get("sha256"))
    for item in artifacts:
        if str(item.get("kind") or "") in {
            "assembled_video",
            "provider_video",
            "high_fidelity_qc_extension",
        }:
            continue
        add_digest(item.get("sha256"))
    if not current_run_source_sha256s:
        raise ValueError(
            "active high-fidelity QC cannot resolve current run source artifacts"
        )
    return final_output_sha256, current_run_source_sha256s


def _qc_evaluator_identity(adapter: Any, context: Any) -> dict[str, Any]:
    """Resolve the deployment-owned semantic evaluator identity.

    A production QC receipt may not choose its own identity.  The authority is
    supplied either by the lease context or by the concrete evaluator nested in
    the deployed QC capability.  This keeps custom QC adapters equivalent to
    ``FfmpegQcEngine`` without coupling the stage bridge to one implementation.
    """

    candidates: list[Any] = [
        getattr(context, "high_fidelity_qc_evaluator_identity", None),
        getattr(adapter, "semantic_qc_evaluator_identity", None),
        getattr(adapter, "evaluator_identity", None),
    ]
    for nested_name in ("semantic_qc_evaluator", "evaluator"):
        nested = getattr(adapter, nested_name, None)
        if nested is None:
            continue
        candidates.append(getattr(nested, "capability_identity", None))
    adapter_identity = getattr(adapter, "capability_identity", None)
    if callable(adapter_identity):
        adapter_identity = adapter_identity()
    if isinstance(adapter_identity, Mapping):
        for key in (
            "semantic_qc_evaluator_identity",
            "evaluator_identity",
            "semantic_qc_evaluator",
            "evaluator",
        ):
            candidates.append(adapter_identity.get(key))
        dependencies = adapter_identity.get("dependencies")
        if isinstance(dependencies, Mapping):
            candidates.extend(
                dependencies.get(key)
                for key in ("semantic_qc_evaluator", "evaluator")
            )

    for candidate in candidates:
        if callable(candidate):
            candidate = candidate()
        if not isinstance(candidate, Mapping):
            continue
        identity = dict(candidate)
        if any(
            not str(identity.get(field) or "").strip()
            for field in ("implementation", "version", "model_id")
        ):
            continue
        if _SHA256.fullmatch(str(identity.get("model_sha256") or "")) is None:
            continue
        binding = str(identity.get("evidence_binding") or "")
        if binding and (not binding.startswith("usfr-") or not binding.endswith("/v1")):
            continue
        return identity
    raise ValueError(
        "active production high-fidelity QC requires a deployment-owned evaluator identity"
    )


def _qc_evaluator_request_payload(
    *,
    final_output_sha256: str,
    current_run_source_sha256s: set[str],
    input_artifacts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the same canonical evaluator request used by FfmpegQcEngine."""

    return {
        "schema_version": "high-fidelity-qc-evaluator-request/v1",
        "final_output_sha256": final_output_sha256,
        "current_run_source_sha256s": sorted(current_run_source_sha256s),
        "input_artifact_sha256s": sorted(
            str(item.get("sha256") or "").lower()
            for item in input_artifacts
            if isinstance(item, Mapping)
            and _SHA256.fullmatch(str(item.get("sha256") or "").lower()) is not None
        ),
    }


def _require_active_high_fidelity_qc(
    value: Mapping[str, Any],
    *,
    context: Any,
    input_artifacts: list[Mapping[str, Any]],
    adapter: Any,
    production: bool,
) -> None:
    """Reject a custom QC adapter that reports only a technical pass."""

    extension = value.get("high_fidelity_qc_extension")
    report = value.get("qc_report")
    if not isinstance(extension, Mapping) and isinstance(report, Mapping):
        extension = report.get("high_fidelity_qc_extension")
    if not isinstance(extension, Mapping):
        raise ValueError("active high-fidelity QC requires the weighted high-fidelity QC extension")
    factors = extension.get("factor_scores")
    if not isinstance(factors, Mapping) or not factors:
        raise ValueError("active high-fidelity QC requires evidence-bearing factor_scores")
    media_bindings = extension.get("media_bindings")
    if not isinstance(media_bindings, Mapping):
        raise ValueError(
            "active high-fidelity QC requires media_bindings for the current final output and Run sources"
        )
    expected_final, expected_sources = _current_qc_media_authority(
        context,
        input_artifacts,
    )
    if str(media_bindings.get("final_output_sha256") or "") != expected_final:
        raise ValueError(
            "active high-fidelity QC media_bindings do not match the current final output artifact"
        )
    declared_sources = media_bindings.get("current_run_source_sha256s")
    if not isinstance(declared_sources, list) or not declared_sources:
        raise ValueError(
            "active high-fidelity QC media_bindings require current run source artifacts"
        )
    declared_source_set = {str(item or "") for item in declared_sources}
    if any(_SHA256.fullmatch(item) is None for item in declared_source_set) or declared_source_set != expected_sources:
        raise ValueError(
            "active high-fidelity QC media_bindings do not contain the exact current Run source set"
        )
    try:
        import importlib.util
        from pathlib import Path

        validator_path = Path(__file__).resolve().parents[1] / "scripts" / "high_fidelity_qc.py"
        spec = importlib.util.spec_from_file_location(
            "usfr_stage_high_fidelity_qc_validator", validator_path
        )
        if spec is None or spec.loader is None:
            raise ValueError("packaged high-fidelity QC validator is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected_identity = (
            _qc_evaluator_identity(adapter, context)
            if production
            else getattr(context, "high_fidelity_qc_evaluator_identity", None)
        )
        module.validate_qc_extension(
            dict(extension),
            require_evaluator_receipt=True,
            expected_evaluator_identity=(
                dict(expected_identity) if isinstance(expected_identity, Mapping) else None
            ),
        )
        if production:
            receipt = extension.get("evaluator_receipt")
            if not isinstance(receipt, Mapping):
                raise ValueError("active production high-fidelity QC requires an evaluator receipt")
            request_payload = _qc_evaluator_request_payload(
                final_output_sha256=expected_final,
                current_run_source_sha256s=expected_sources,
                input_artifacts=input_artifacts,
            )
            expected_request_sha256 = _canonical_sha256(request_payload)
            if str(receipt.get("request_sha256") or "") != expected_request_sha256:
                raise ValueError(
                    "evaluator receipt request SHA does not match the canonical current-run request"
                )

            evaluator_response = value.get("qc_evaluator_response")
            if isinstance(evaluator_response, Mapping):
                response_receipt = evaluator_response.get("evaluator_receipt")
                if not isinstance(response_receipt, Mapping) or dict(response_receipt) != dict(receipt):
                    raise ValueError(
                        "QC evaluator response receipt does not match the weighted extension receipt"
                    )
                response_payload = {
                    key: child
                    for key, child in evaluator_response.items()
                    if key != "evaluator_receipt"
                }
            else:
                response_payload = {
                    key: child for key, child in extension.items() if key != "evaluator_receipt"
                }
            expected_response_sha256 = _canonical_sha256(response_payload)
            if str(receipt.get("response_sha256") or "") != expected_response_sha256:
                raise ValueError(
                    "evaluator receipt response SHA does not match the returned QC evidence"
                )
    except Exception as exc:
        raise ValueError(f"active high-fidelity QC extension validation failed: {exc}") from exc


class BoundStagePort:
    """Tag an existing canonical StagePort with its runtime capabilities.

    This wrapper is required for composite stages such as ``build_script`` and
    ``compile_seedance20_prompt``: it preserves the existing stage handler,
    while ``HighFidelityStageAdapter`` adds Invocation A/B inside that handler.
    It does not replace script/storyboard work with a standalone compiler call.
    """

    def __init__(self, stage: str, handler: Any) -> None:
        required = STAGE_CAPABILITY_REQUIREMENTS.get(stage)
        if required is None:
            raise ValueError(f"stage {stage!r} has no capability binding")
        if stage not in _COMPOSITE_CAPABILITY_STAGES:
            raise ValueError(f"stage {stage!r} must execute through CapabilityStagePort")
        if handler is None:
            raise ValueError("existing stage handler is required")
        self.stage = stage
        self.handler = handler
        self.capability_names = tuple(required)

    def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        method = getattr(self.handler, "run", None)
        if method is None or not callable(method) or callable(self.handler):
            method = self.handler
        if not callable(method):
            raise ValueError("existing stage handler must be callable or implement run()")
        value = _call(method, context=context, input_artifacts=input_artifacts)
        if not isinstance(value, Mapping) or not value:
            raise ValueError(f"{self.stage} existing stage handler returned no executable output")
        return value


class CapabilityStagePort:
    """Thin executor that keeps existing stage names and calls real ports."""

    def __init__(
        self,
        stage: str,
        capability_ports: Mapping[str, Any],
        *,
        manifest: Mapping[str, Any] | None = None,
        production: bool = False,
        profile_active: bool = False,
    ) -> None:
        required = STAGE_CAPABILITY_REQUIREMENTS.get(stage)
        if required is None:
            raise ValueError(f"stage {stage!r} has no capability binding")
        if stage not in _DIRECT_CAPABILITY_STAGES:
            raise ValueError(
                f"stage {stage!r} is composite and must use BoundStagePort plus HighFidelityStageAdapter"
            )
        self.stage = stage
        self.capability_names = tuple(required)
        self.profile_active = bool(profile_active)
        self.production = bool(production)
        self._ports = validate_runtime_capability_ports(
            capability_ports,
            manifest=manifest,
            production=production,
            profile_active=profile_active,
        )
        for name in required:
            if name not in self._ports:
                raise ValueError(f"stage {stage} requires capability {name}")

    def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        if self.stage == "analyze_dynamics":
            dynamics = _require_result(
                _call(self._ports["dynamics_analyzer"].analyze, context=context, input_artifacts=input_artifacts),
                "dynamics_analyzer",
                operation=self.stage,
            )
            analysis_scope = getattr(context, "analysis_scope", None)
            tools = analysis_scope.get("tools") if isinstance(analysis_scope, Mapping) else None
            asr_decision = tools.get("source_asr") if isinstance(tools, Mapping) else None
            if isinstance(asr_decision, Mapping) and asr_decision.get("status") == "skipped":
                return {
                    "status": "ready",
                    "capabilities": ["dynamics_analyzer"],
                    "source_dynamics_analysis": dict(dynamics["source_dynamics_analysis"]),
                    "capability_receipts": {"dynamics_analyzer": dict(dynamics)},
                    "skipped_tools": [{
                        "tool": "source_asr",
                        "reason": str(asr_decision.get("reason") or "pre_route_skipped"),
                    }],
                }
            audio = _require_result(
                _call(
                    self._ports["asr_transcriber"].transcribe,
                    context=context,
                    input_artifacts=input_artifacts,
                    dynamics=dynamics,
                ),
                "asr_transcriber",
                operation=self.stage,
            )
            if self.profile_active:
                _require_high_fidelity_dynamics_extension(dynamics)
            audio_contract = dict(audio["audio_contract"])
            source_dynamics_analysis = dict(dynamics["source_dynamics_analysis"])
            try:
                source_content_timeline = build_source_content_timeline(
                    source_video_sha256=_source_video_sha256(context, dynamics),
                    source_dynamics_analysis=source_dynamics_analysis,
                    audio_contract=audio_contract,
                )
            except SourceContentTimelineError as exc:
                raise ValueError(f"source content timeline is invalid: {exc}") from exc
            performance_audio: dict[str, Any] | None = None
            published_artifacts: list[dict[str, Any]] = []
            source_audio_sha256 = audio_contract.get("source_audio_sha256")
            if source_audio_sha256:
                performance_audio = build_audio_evidence_contracts(
                    source_audio_sha256=str(source_audio_sha256),
                    source_duration_ms=audio_contract.get("source_duration_ms"),
                    audio_contract=audio_contract,
                )
                for kind in (
                    "performance_audio_source_contract",
                    "audio_lyrics_beat_contract",
                ):
                    published = _publish_internal_json_contract(
                        context=context,
                        kind=kind,
                        value=performance_audio[kind],
                    )
                    if published is not None:
                        published_artifacts.append(published)
            elif self.profile_active:
                raise ValueError(
                    "active source-audio replication requires an extracted source_audio_sha256"
                )
            published_timeline = _publish_internal_json_contract(
                context=context,
                kind="source_content_timeline",
                value=source_content_timeline,
            )
            if published_timeline is not None:
                published_artifacts.append(published_timeline)
            result = {
                "status": "ready",
                "capabilities": list(sorted(self.capability_names)),
                "source_dynamics_analysis": source_dynamics_analysis,
                "audio_contract": audio_contract,
                "source_content_timeline": source_content_timeline,
                "capability_receipts": {
                    "dynamics_analyzer": dict(dynamics),
                    "asr_transcriber": dict(audio),
                },
            }
            if performance_audio is not None:
                result["source_audio_mode"] = "source_audio_replicate_v1"
                result.update(performance_audio)
            if published_artifacts:
                result["published_artifacts"] = published_artifacts
            return result
        if (
            self.stage == "resolve_ui_evidence"
            and hasattr(context, "timeline_regions")
            and not _context_has_generated_ui(context)
        ):
            return {
                "status": "skipped",
                "skipped_reason": "no_generated_ui_region",
                "capabilities": list(sorted(self.capability_names)),
            }
        name = self.capability_names[0]
        adapter = self._ports[name]
        method_name = {
            "resolve_ui_evidence": "render_and_verify",
            "build_script": "invoke_a",
            "compile_seedance20_prompt": "invoke_b",
            "splice_timeline": "compose",
            "run_qc": "run",
        }[self.stage]
        result = _require_result(
            _call(getattr(adapter, method_name), context=context, input_artifacts=input_artifacts),
            name,
            operation=self.stage,
        )
        if self.stage == "resolve_ui_evidence" and self.profile_active and _context_has_generated_ui(context):
            _require_active_generated_ui_video(result)
        if self.stage == "run_qc" and self.profile_active:
            _require_active_high_fidelity_qc(
                result,
                context=context,
                input_artifacts=input_artifacts,
                adapter=adapter,
                production=self.production,
            )
        output = {
            "status": "ready",
            "capabilities": [name],
            "capability_receipt": dict(result),
        }
        # Keep canonical evidence at the stage boundary so downstream
        # artifact/QC handlers do not need to know this adapter's envelope.
        output.update(dict(result))
        output["status"] = "ready"
        return output


__all__ = [
    "REQUIRED_CAPABILITY_METHODS",
    "STAGE_CAPABILITY_REQUIREMENTS",
    "BoundRuntimeCapability",
    "BoundStagePort",
    "CapabilityStagePort",
    "validate_runtime_capability_ports",
    "validate_provider_callable_binding",
    "validate_stage_port_bindings",
]
