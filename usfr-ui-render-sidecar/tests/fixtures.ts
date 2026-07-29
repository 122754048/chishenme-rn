import {readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';

import type {SourceUiInteractionContract} from '../src/contracts';
import {bytesSha256, canonicalSha256} from '../src/digests';

export const sourceInteractionContract = (
  options: {frames?: number; fps?: number; width?: number; height?: number} = {},
): SourceUiInteractionContract => {
  const frames = options.frames ?? 24;
  const fps = options.fps ?? 30;
  const width = options.width ?? 180;
  const height = options.height ?? 320;
  return {
  schema_version: 'source-ui-interaction/v1' as const,
  region_id: 'ui-001',
  source_window_us: {start: 0, end_exclusive: Math.round((frames / fps) * 1_000_000)},
  frame_window: {start: 0, end_exclusive: frames},
  source_fps: {num: fps, den: 1},
  display_viewport: [width, height] as [number, number],
  ui_roi: {
    x: 0,
    y: 0,
    width,
    height,
    coordinate_space: 'display_pixels' as const,
  },
  language: {source: 'en', target: 'en', mode: 'preserve_source' as const},
  text_encoding: {encoding: 'utf-8' as const, replacement_glyphs_forbidden: true as const},
  motion: {
    capture_scope: 'ui_roi_only' as const,
    track_policy: 'source_frame_locked' as const,
    supported_actions: ['drag', 'scroll', 'bounce', 'scale', 'rotate', 'opacity', 'tap'] as [
      'drag',
      'scroll',
      'bounce',
      'scale',
      'rotate',
      'opacity',
      'tap',
    ],
  },
  validation: {
    mode: 'basic_anchor_only' as const,
    automatic_retry: false as const,
    anchor_frames: [0, frames - 1] as [number, number],
    speed_profile: 'fast_lightweight_v1' as const,
    visual_accuracy_target_percent: 90 as const,
    maximum_visual_deviation_percent: 20 as const,
    text_accuracy_required_percent: 100 as const,
  },
  };
};

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

const runFfmpeg = (args: string[]) => {
  const result = spawnSync('ffmpeg', args, {encoding: 'utf8'});
  if (result.status !== 0) {
    throw new Error(result.stderr || 'FFmpeg fixture generation failed');
  }
};

export const realRequestFixture = async (
  workDir: string,
  options: {frames?: number; fps?: number; width?: number; height?: number; copy?: string[]} = {},
) => {
  const frames = options.frames ?? 12;
  const fps = options.fps ?? 12;
  const width = options.width ?? 180;
  const height = options.height ?? 320;
  const copy = options.copy ?? ['立即购买'];
  const imagePath = join(workDir, 'target.png');
  const videoPath = join(workDir, 'reference.mp4');
  runFfmpeg([
    '-y', '-loglevel', 'error', '-f', 'lavfi', '-i',
    `color=c=0x18202d:s=${width}x${height}:r=1:d=1`,
    '-vf', `drawbox=x=18:y=70:w=84:h=118:color=0x31d18b:t=fill`,
    '-frames:v', '1', '-update', '1', imagePath,
  ]);
  runFfmpeg([
    '-y', '-loglevel', 'error', '-f', 'lavfi', '-i',
    `color=c=0x202531:s=${width}x${height}:r=${fps}:d=${frames / fps}`,
    '-vf', `drawbox=x=18+30*t:y=70:w=84:h=118:color=white:t=fill`,
    '-frames:v', String(frames), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', videoPath,
  ]);
  const image = await readFile(imagePath);
  const video = await readFile(videoPath);
  const interaction = sourceInteractionContract({frames, fps, width, height});
  const core = {
    schema_version: 'usfr-ui-render-evidence/v1' as const,
    source_sha256: bytesSha256(image),
    source_content_type: 'image/png',
    source_base64: image.toString('base64'),
    ui_truth_card: {
      approved_copy: copy,
      states: [
        {
          state_id: 'state-001',
          frame_ms: 0,
          expected_text: copy,
          expected_layout: copy.map((text, index) => ({
            element_id: `copy-${index + 1}`,
            role: 'button',
            text,
            bbox: [20, 20 + index * 44, width - 20, 58 + index * 44] as [number, number, number, number],
            font_size: 16,
            color: '#ffffff',
            background_color: '#111827',
            text_align: 'center' as const,
          })),
        },
      ],
    },
    ui_render_contract: {
      viewport: [width, height] as [number, number],
      state_sequence: ['state-001'],
      source_ui_interaction_contract: interaction,
    },
    motion_reference: {
      sha256: bytesSha256(video),
      content_type: 'video/mp4' as const,
      video_base64: video.toString('base64'),
      source_ui_interaction_contract: interaction,
    },
    expected_model: {id: 'usfr-ui-remotion-opencv', sha256: '3'.repeat(64)},
  };
  const request = {...core, request_sha256: canonicalSha256(core)};
  await writeFile(join(workDir, 'request.json'), JSON.stringify(request), 'utf8');
  return request;
};
