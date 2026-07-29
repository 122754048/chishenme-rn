import {createHash} from 'node:crypto';

import request from 'supertest';
import {describe, expect, it, vi} from 'vitest';

import {createApp, type SidecarConfig} from '../src/server';
import {validRequest} from './fixtures';

const model = {id: 'usfr-ui-remotion-opencv', sha256: '3'.repeat(64)};
const config: SidecarConfig = {
  host: '127.0.0.1',
  port: 47821,
  apiToken: 'private-token',
  idleTimeoutSeconds: 0,
  maxRequestBytes: 16 * 1024 * 1024,
  model,
  pythonExecutable: 'python',
  projectRoot: process.cwd(),
};

const responseFor = (parsed: ReturnType<typeof validRequest>) => {
  const video = Buffer.from('video-bytes');
  return {
    schema_version: 'usfr-ui-render-evidence/v1' as const,
    request_sha256: parsed.request_sha256,
    source_sha256: parsed.source_sha256,
    ui_truth_card: parsed.ui_truth_card,
    ui_render_contract: parsed.ui_render_contract,
    video_base64: video.toString('base64'),
    video_sha256: createHash('sha256').update(video).digest('hex'),
    state_sequence: parsed.ui_render_contract.state_sequence,
    motion_track_sha256: '4'.repeat(64),
    model,
  };
};

describe('sidecar HTTP service', () => {
  it('reports CPU-only dependency readiness', async () => {
    const app = createApp(config, vi.fn(), async () => ({ready: true, checks: {ffmpeg: true}}));
    const response = await request(app).get('/readyz').expect(200);

    expect(response.body).toMatchObject({ready: true, cpu_only: true});
  });

  it('requires the private bearer token for rendering', async () => {
    const app = createApp(config, vi.fn());

    await request(app).post('/v1/render').send(validRequest()).expect(401);
  });

  it('rejects a request whose canonical request hash is wrong', async () => {
    const app = createApp(config, vi.fn());
    const payload = validRequest();
    payload.ui_truth_card.approved_copy = ['Changed after hashing'];

    await request(app)
      .post('/v1/render')
      .set('Authorization', 'Bearer private-token')
      .send(payload)
      .expect(422);
  });

  it('calls the render pipeline once and validates its response', async () => {
    const pipeline = vi.fn(async (parsed) => responseFor(parsed));
    const app = createApp(config, pipeline);
    const payload = validRequest();
    const response = await request(app)
      .post('/v1/render')
      .set('Authorization', 'Bearer private-token')
      .send(payload)
      .expect(200);

    expect(pipeline).toHaveBeenCalledTimes(1);
    expect(response.body.request_sha256).toBe(payload.request_sha256);
  });

  it('starts UI artifact retention only after the final video is reported', async () => {
    const retention = {
      markFinalized: vi.fn(async () => ({
        schema_version: 'usfr-ui-retention/v1' as const,
        request_sha256: 'a'.repeat(64),
        final_video_sha256: 'b'.repeat(64),
        finalized_at_ms: 1_000,
        purge_after_ms: 86_401_000,
      })),
    };
    const app = createApp(config, vi.fn(), undefined, retention);

    await request(app)
      .post('/v1/retention/finalized')
      .set('Authorization', 'Bearer private-token')
      .send({request_sha256: 'a'.repeat(64), final_video_sha256: 'b'.repeat(64)})
      .expect(202);

    expect(retention.markFinalized).toHaveBeenCalledWith(
      expect.objectContaining({requestSha256: 'a'.repeat(64), finalVideoSha256: 'b'.repeat(64)}),
    );
  });
});
