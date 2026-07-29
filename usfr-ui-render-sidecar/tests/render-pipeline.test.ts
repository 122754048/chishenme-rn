import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

import {describe, expect, it} from 'vitest';

import {bytesSha256} from '../src/digests';
import {renderRequest} from '../src/render-pipeline';
import {realRequestFixture} from './fixtures';

describe('render pipeline', () => {
  it('returns a bound real MP4 and reuses its content-addressed cache', async () => {
    const workDir = await mkdtemp(join(tmpdir(), 'usfr-pipeline-test-'));
    try {
      const payload = await realRequestFixture(workDir, {frames: 8, fps: 8});
      const config = {
        projectRoot: process.cwd(),
        runtimeRoot: join(workDir, 'runtime'),
        pythonExecutable: join(process.cwd(), '.venv', 'Scripts', 'python.exe'),
        model: payload.expected_model,
        renderTimeoutMs: 180_000,
      };
      const first = await renderRequest(payload, config);
      const second = await renderRequest(payload, config);
      const video = Buffer.from(first.video_base64, 'base64');

      expect(bytesSha256(video)).toBe(first.video_sha256);
      expect(first.motion_track_sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(first.state_sequence).toEqual(['state-001']);
      expect(first.receipt.cache_hit).toBe(false);
      expect(second.receipt.cache_hit).toBe(true);
      expect(await readFile(first.receipt.output_path)).toEqual(video);
    } finally {
      await rm(workDir, {recursive: true, force: true});
    }
  }, 240_000);
});
