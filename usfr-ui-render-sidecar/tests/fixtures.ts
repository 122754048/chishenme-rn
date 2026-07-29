import {canonicalSha256} from '../src/digests';

export const sourceInteractionContract = () => ({
  schema_version: 'source-ui-interaction/v1' as const,
  region_id: 'ui-001',
  source_window_us: {start: 0, end_exclusive: 800_000},
  frame_window: {start: 0, end_exclusive: 24},
  source_fps: {num: 30, den: 1},
  display_viewport: [180, 320],
  ui_roi: {
    x: 0,
    y: 0,
    width: 180,
    height: 320,
    coordinate_space: 'display_pixels' as const,
  },
  language: {source: 'en', target: 'en', mode: 'preserve_source' as const},
  text_encoding: {encoding: 'utf-8' as const, replacement_glyphs_forbidden: true as const},
  motion: {
    capture_scope: 'ui_roi_only' as const,
    track_policy: 'source_frame_locked' as const,
    supported_actions: ['drag', 'scroll', 'bounce', 'scale', 'rotate', 'opacity', 'tap'],
  },
  validation: {
    mode: 'basic_anchor_only' as const,
    automatic_retry: false as const,
    anchor_frames: [0, 23],
  },
});

export const validRequest = (approvedCopy: string[] = ['Buy now']) => {
  const core = {
    schema_version: 'usfr-ui-render-evidence/v1' as const,
    source_sha256: '1'.repeat(64),
    source_content_type: 'image/png',
    source_base64: 'aW1hZ2U=',
    ui_truth_card: {
      approved_copy: approvedCopy,
      states: [
        {
          state_id: 'state-001',
          frame_ms: 0,
          expected_text: approvedCopy,
          expected_layout: [],
        },
      ],
    },
    ui_render_contract: {
      viewport: [180, 320],
      state_sequence: ['state-001'],
      source_ui_interaction_contract: sourceInteractionContract(),
    },
    motion_reference: {
      sha256: '2'.repeat(64),
      content_type: 'video/mp4' as const,
      video_base64: 'dmlkZW8=',
      source_ui_interaction_contract: sourceInteractionContract(),
    },
    expected_model: {id: 'usfr-ui-remotion-opencv', sha256: '3'.repeat(64)},
  };
  return {...core, request_sha256: canonicalSha256(core)};
};
