"""Stateless video-generation runtime for Universal Source Fidelity."""

from .errors import ReplicationError
from .capabilities import (
    REQUIRED_CAPABILITIES,
    build_stage_capability_manifest,
    validate_stage_capability_manifest,
)
from .artifacts import LocalArtifactStore
from .intake import ObjectStoreProbe, bind_uploaded_slots
from .media_materializer import MediaMaterializer, MaterializedMedia, ObjectStoreMediaReader
from .high_fidelity_ports import HighFidelityStageAdapter
from .high_fidelity_projection import build_invocation_a_request
from .ephemeral_service import ReplicationService
from .seedance_invocations import SeedanceInvocationAdapter
from .bundle_resolver import BundleEntry, BundleResolverError, ImmutableBundleResolver
from .ephemeral_worker import EphemeralStageContext, EphemeralWorkerManager
from .ephemeral_driver import EphemeralStageDriver
from .orchestrator import (
    bind_source_overlay_contract_to_timeline,
    validate_timeline_region_persistence,
)
from .overlay_mapping import OverlayMappingError, build_overlay_render_mapping
from .overlay_renderer import DeterministicOverlayRenderer, OverlayRenderError
from .real_capabilities import (
    CapabilityUnavailable,
    FfmpegDynamicsAnalyzer,
    WhisperAsrTranscriber,
    BundledAppStoreEvidenceParser,
    DeterministicUiRenderer,
    FfmpegCompositor,
    FfmpegQcEngine,
)
from .audio_backends import AudioBackendUnavailable, EvidenceBoundHttpAudioEventBackend
from .vision_backends import (
    VisionBackendUnavailable,
    EvidenceBoundHttpOcrBackend,
    EvidenceBoundHttpUiRenderer,
    EvidenceBoundHttpVlmBackend,
)
from .deployment_bootstrap import (
    DeploymentBootstrapError,
    DeploymentRuntime,
    build_http_app,
    load_deployment_runtime,
    run_worker,
)

__all__ = [
    "ReplicationError",
    "REQUIRED_CAPABILITIES",
    "build_stage_capability_manifest",
    "validate_stage_capability_manifest",
    "ReplicationService",
    "LocalArtifactStore",
    "ObjectStoreProbe",
    "bind_uploaded_slots",
    "MediaMaterializer",
    "MaterializedMedia",
    "ObjectStoreMediaReader",
    "HighFidelityStageAdapter",
    "build_invocation_a_request",
    "SeedanceInvocationAdapter",
    "BundleEntry",
    "BundleResolverError",
    "ImmutableBundleResolver",
    "EphemeralStageContext",
    "EphemeralWorkerManager",
    "EphemeralStageDriver",
    "bind_source_overlay_contract_to_timeline",
    "validate_timeline_region_persistence",
    "OverlayMappingError",
    "build_overlay_render_mapping",
    "DeterministicOverlayRenderer",
    "OverlayRenderError",
    "CapabilityUnavailable",
    "FfmpegDynamicsAnalyzer",
    "WhisperAsrTranscriber",
    "BundledAppStoreEvidenceParser",
    "DeterministicUiRenderer",
    "FfmpegCompositor",
    "FfmpegQcEngine",
    "AudioBackendUnavailable",
    "EvidenceBoundHttpAudioEventBackend",
    "VisionBackendUnavailable",
    "EvidenceBoundHttpOcrBackend",
    "EvidenceBoundHttpUiRenderer",
    "EvidenceBoundHttpVlmBackend",
    "DeploymentBootstrapError",
    "DeploymentRuntime",
    "build_http_app",
    "load_deployment_runtime",
    "run_worker",
]
