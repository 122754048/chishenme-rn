import {createServer} from 'node:http';
import {access, mkdir, readFile, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';

import {
  RenderRequestSchema,
  RenderResponseSchema,
  type RenderRequest,
  type RenderResponse,
} from './contracts';
import {bytesSha256, canonicalSha256} from './digests';
import {runPythonExtractor} from './python-runner';
import {renderReplica} from './remotion/render';

export type RenderPipelineConfig = {
  projectRoot: string;
  runtimeRoot?: string;
  pythonExecutable: string;
  model: {id: string; sha256: string};
  renderTimeoutMs?: number;
};

export type RenderPipelineResponse = RenderResponse & {
  receipt: {
    cache_hit: boolean;
    output_path: string;
    cpu_only: true;
    extraction_ms: number;
    render_ms: number;
    total_ms: number;
  };
};

export class RenderPipelineError extends Error {
  public constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

const decodeAndVerify = (encoded: string, expectedSha256: string, label: string): Buffer => {
  const bytes = Buffer.from(encoded, 'base64');
  if (bytes.length === 0 || bytesSha256(bytes) !== expectedSha256) {
    throw new RenderPipelineError('MEDIA_DIGEST_MISMATCH', `${label} bytes do not match their SHA-256`);
  }
  return bytes;
};

const probeOutput = (path: string, width: number, height: number, frames: number): void => {
  const result = spawnSync(
    'ffprobe',
    [
      '-v',
      'error',
      '-count_frames',
      '-select_streams',
      'v:0',
      '-show_entries',
      'stream=codec_name,width,height,nb_read_frames',
      '-of',
      'json',
      path,
    ],
    {encoding: 'utf8'},
  );
  if (result.status !== 0) {
    throw new RenderPipelineError('OUTPUT_INVALID', result.stderr || 'FFprobe rejected the output');
  }
  const stream = JSON.parse(result.stdout).streams?.[0];
  if (
    stream?.codec_name !== 'h264' ||
    Number(stream.width) !== width ||
    Number(stream.height) !== height ||
    Number(stream.nb_read_frames) !== frames
  ) {
    throw new RenderPipelineError('OUTPUT_INVALID', 'rendered video does not match frame contract');
  }
};

const withMotionServer = async <T>(path: string, callback: (url: string) => Promise<T>): Promise<T> => {
  const bytes = await readFile(path);
  const server = createServer((request, response) => {
    if (request.url !== '/motion.mp4') {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, {
      'Content-Type': 'video/mp4',
      'Content-Length': bytes.length,
      'Cache-Control': 'no-store',
    });
    response.end(bytes);
  });
  await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
  const address = server.address();
  if (!address || typeof address === 'string') {
    server.close();
    throw new RenderPipelineError('RENDER_FAILED', 'internal motion server did not bind TCP');
  }
  try {
    return await callback(`http://127.0.0.1:${address.port}/motion.mp4`);
  } finally {
    await new Promise<void>((done, reject) =>
      server.close((error) => (error ? reject(error) : done())),
    );
  }
};

const cachedResponse = async (
  parsed: RenderRequest,
  responsePath: string,
  outputPath: string,
): Promise<RenderPipelineResponse | undefined> => {
  try {
    const stored = JSON.parse(await readFile(responsePath, 'utf8')) as RenderPipelineResponse;
    const video = await readFile(outputPath);
    if (stored.video_sha256 !== bytesSha256(video) || stored.request_sha256 !== parsed.request_sha256) {
      return undefined;
    }
    return {
      ...stored,
      video_base64: video.toString('base64'),
      receipt: {...stored.receipt, cache_hit: true},
    };
  } catch {
    return undefined;
  }
};

export const renderRequest = async (
  request: RenderRequest,
  config: RenderPipelineConfig,
): Promise<RenderPipelineResponse> => {
  const startedAt = performance.now();
  const parsed = RenderRequestSchema.parse(request);
  const {request_sha256: declaredRequestSha, ...requestCore} = parsed;
  if (canonicalSha256(requestCore) !== declaredRequestSha) {
    throw new RenderPipelineError('REQUEST_DIGEST_MISMATCH', 'request SHA-256 does not match canonical request bytes');
  }
  if (parsed.expected_model.id !== config.model.id || parsed.expected_model.sha256 !== config.model.sha256) {
    throw new RenderPipelineError('MODEL_IDENTITY_MISMATCH', 'expected model identity is not installed');
  }
  const targetBytes = decodeAndVerify(parsed.source_base64, parsed.source_sha256, 'target UI image');
  const referenceBytes = decodeAndVerify(
    parsed.motion_reference.video_base64,
    parsed.motion_reference.sha256,
    'motion reference video',
  );
  const runtimeRoot = resolve(config.runtimeRoot ?? resolve(config.projectRoot, '.runtime'));
  const jobDir = resolve(runtimeRoot, 'jobs', parsed.request_sha256);
  const outputPath = resolve(jobDir, 'output-ui.mp4');
  const responsePath = resolve(jobDir, 'response.json');
  await mkdir(jobDir, {recursive: true});
  const cached = await cachedResponse(parsed, responsePath, outputPath);
  if (cached) {
    return cached;
  }

  const targetPath = resolve(jobDir, 'target.png');
  const referencePath = resolve(jobDir, 'motion-reference.mp4');
  const contractPath = resolve(jobDir, 'source-ui-interaction.json');
  const extractionDir = resolve(jobDir, 'motion');
  await writeFile(targetPath, targetBytes);
  await writeFile(referencePath, referenceBytes);
  await writeFile(
    contractPath,
    JSON.stringify(parsed.motion_reference.source_ui_interaction_contract),
    'utf8',
  );

  const extractionStarted = performance.now();
  const extracted = await runPythonExtractor({
    projectRoot: config.projectRoot,
    pythonExecutable: config.pythonExecutable,
    sourcePath: referencePath,
    targetPath,
    contractPath,
    outputDir: extractionDir,
    timeoutMs: config.renderTimeoutMs ?? 300_000,
  });
  const extractionMs = Math.round(performance.now() - extractionStarted);
  await access(extracted.video_path);
  const trackBytes = await readFile(extracted.track_path);
  const motionTrackSha256 = bytesSha256(trackBytes);
  const interaction = parsed.motion_reference.source_ui_interaction_contract;
  const frames = interaction.frame_window.end_exclusive - interaction.frame_window.start;
  const fps = interaction.source_fps.num / interaction.source_fps.den;
  const [width, height] = parsed.ui_render_contract.viewport;
  const renderStarted = performance.now();
  await withMotionServer(extracted.video_path, async (motionVideoUrl) =>
    renderReplica(
      {
        motionVideoUrl,
        width,
        height,
        fps,
        durationInFrames: frames,
        states: parsed.ui_truth_card.states,
        transitionShell: {},
      },
      outputPath,
    ),
  );
  const renderMs = Math.round(performance.now() - renderStarted);
  probeOutput(outputPath, width, height, frames);
  const video = await readFile(outputPath);
  const response: RenderPipelineResponse = {
    schema_version: 'usfr-ui-render-evidence/v1',
    request_sha256: parsed.request_sha256,
    source_sha256: parsed.source_sha256,
    ui_truth_card: parsed.ui_truth_card,
    ui_render_contract: parsed.ui_render_contract,
    video_base64: video.toString('base64'),
    video_sha256: bytesSha256(video),
    state_sequence: parsed.ui_render_contract.state_sequence,
    motion_track_sha256: motionTrackSha256,
    model: config.model,
    receipt: {
      cache_hit: false,
      output_path: outputPath,
      cpu_only: true,
      extraction_ms: extractionMs,
      render_ms: renderMs,
      total_ms: Math.round(performance.now() - startedAt),
    },
  };
  RenderResponseSchema.parse(response);
  await writeFile(
    responsePath,
    JSON.stringify({...response, video_base64: ''}),
    'utf8',
  );
  return response;
};
