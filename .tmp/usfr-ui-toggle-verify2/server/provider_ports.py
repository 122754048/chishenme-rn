from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from .ephemeral_worker import EphemeralStageContext


class ProviderPort(Protocol):
    def create_asset(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def create_video(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def lookup(self, intent: Mapping[str, Any]) -> Mapping[str, Any]: ...


class StagePort(Protocol):
    """Stage adapter boundary used by deployed workers.

    A stage receives a job-scoped :class:`EphemeralStageContext` and immutable
    input descriptors.  It must materialize media through the context rather
    than accepting client/workstation paths.  The context also exposes the
    pinned profile snapshot and the internal Invocation A/B bridge. Expensive
    adapters must call ``context.authorize_tool(...)`` before invocation and
    return a bound ``tool_execution_receipts`` row for worker-side enforcement.
    """

    def run(
        self,
        *,
        context: EphemeralStageContext,
        input_artifacts: list[Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...


class CapabilityIdentityPort(Protocol):
    """Identity required to bind an executable capability to its manifest."""

    def capability_identity(self) -> Mapping[str, Any]: ...


class DynamicsAnalyzerPort(CapabilityIdentityPort, Protocol):
    def analyze(self, *, context: EphemeralStageContext, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]: ...


class AsrTranscriberPort(CapabilityIdentityPort, Protocol):
    def transcribe(self, *, context: EphemeralStageContext, input_artifacts: list[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]: ...


class OcrUiRendererPort(CapabilityIdentityPort, Protocol):
    def render_and_verify(self, *, context: EphemeralStageContext, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]: ...


class Seedance20CompilerPort(CapabilityIdentityPort, Protocol):
    def invoke_a(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def invoke_b(self, **kwargs: Any) -> Mapping[str, Any]: ...


class CompositorPort(CapabilityIdentityPort, Protocol):
    def compose(self, *, context: EphemeralStageContext, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]: ...


class QcEnginePort(CapabilityIdentityPort, Protocol):
    def run(self, *, context: EphemeralStageContext, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]: ...


class ProviderAdapterPort(CapabilityIdentityPort, Protocol):
    """Manifest-bound paid Provider client.

    Production callers must pass these exact bound methods through
    ``validate_provider_callable_binding``; a second client instance or a
    free-standing lambda is not an equivalent adapter.
    """

    def create_asset(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def create_video(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def lookup(self, intent: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def download(self, task_id_or_url: str, destination: str | Path) -> Mapping[str, Any]: ...


class ArtifactPort(Protocol):
    """Immutable byte publication boundary used before production QC."""

    def put_stream(
        self,
        *,
        run_id: str,
        artifact_id: str,
        stream: Any,
        content_type: str,
        expected_sha256: str | None = None,
    ) -> Mapping[str, Any]: ...


class ActivationEvidenceReceiptVerifierPort(Protocol):
    """Server-owned resolver for immutable activation report receipts.

    Implementations re-read the private artifact/ledger and return authoritative
    metadata for the exact receipt.  A client-provided mapping or status flag is
    not an implementation of this boundary.
    """

    def __call__(self, receipt: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


__all__ = [
    "ProviderPort",
    "StagePort",
    "CapabilityIdentityPort",
    "DynamicsAnalyzerPort",
    "AsrTranscriberPort",
    "OcrUiRendererPort",
    "Seedance20CompilerPort",
    "CompositorPort",
    "QcEnginePort",
    "ProviderAdapterPort",
    "ArtifactPort",
    "ActivationEvidenceReceiptVerifierPort",
]
