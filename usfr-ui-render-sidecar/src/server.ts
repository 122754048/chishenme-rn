import {timingSafeEqual} from 'node:crypto';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';

import express, {type Express, type NextFunction, type Request, type Response} from 'express';
import {ZodError} from 'zod';

import {loadConfig, type SidecarConfig} from './config';
import {RenderRequestSchema, RenderResponseSchema, type RenderRequest} from './contracts';
import {canonicalSha256} from './digests';
import {renderRequest, RenderPipelineError, type RenderPipelineResponse} from './render-pipeline';
import {SidecarRetentionStore} from './retention';

export type {SidecarConfig} from './config';

type RenderPipeline = (request: RenderRequest) => Promise<RenderPipelineResponse | unknown>;
type Readiness = () => Promise<{ready: boolean; checks: Record<string, boolean>}>;
type RetentionStore = Pick<SidecarRetentionStore, 'markFinalized'> & {
  sweep?: (nowMs?: number) => Promise<string[]>;
};

const sha256 = /^[0-9a-f]{64}$/;

const secureTokenMatch = (supplied: string, expected: string): boolean => {
  const left = Buffer.from(supplied, 'utf8');
  const right = Buffer.from(expected, 'utf8');
  return left.length === right.length && timingSafeEqual(left, right);
};

export const checkReadiness = async (config: SidecarConfig) => {
  const commandReady = (command: string, args: string[]): boolean =>
    spawnSync(command, args, {encoding: 'utf8', windowsHide: true}).status === 0;
  const checks = {
    ffmpeg: commandReady('ffmpeg', ['-version']),
    ffprobe: commandReady('ffprobe', ['-version']),
    python_opencv: commandReady(config.pythonExecutable, ['-c', 'import cv2, numpy']),
    remotion_entry: existsSync(resolve(config.projectRoot, 'src', 'remotion', 'index.tsx')),
  };
  return {ready: Object.values(checks).every(Boolean), checks};
};

export const createApp = (
  config: SidecarConfig,
  pipeline: RenderPipeline = (parsed) =>
    renderRequest(parsed, {
      projectRoot: config.projectRoot,
      runtimeRoot: config.runtimeRoot,
      pythonExecutable: config.pythonExecutable,
      model: config.model,
      renderTimeoutMs: config.renderTimeoutMs,
    }),
  readiness: Readiness = () => checkReadiness(config),
  retention: RetentionStore = new SidecarRetentionStore({
    runtimeRoot: config.runtimeRoot ?? resolve(config.projectRoot, '.runtime'),
    retentionHours: 24,
  }),
): Express => {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({limit: config.maxRequestBytes}));
  app.locals.activity = {active: 0, lastActivityAt: Date.now(), pendingRetention: 0};

  app.get('/readyz', async (_request, response, next) => {
    try {
      const result = await readiness();
      response.status(result.ready ? 200 : 503).json({...result, cpu_only: true, model: config.model});
    } catch (error) {
      next(error);
    }
  });

  app.post('/v1/render', async (request, response, next) => {
    try {
      if (config.apiToken) {
        const authorization = request.header('authorization') ?? '';
        const supplied = authorization.startsWith('Bearer ') ? authorization.slice(7) : '';
        if (!secureTokenMatch(supplied, config.apiToken)) {
          response.status(401).json({error: {code: 'UNAUTHORIZED', message: 'render token is invalid'}});
          return;
        }
      }
      const parsed = RenderRequestSchema.parse(request.body);
      const {request_sha256: declaredRequestSha, ...core} = parsed;
      if (canonicalSha256(core) !== declaredRequestSha) {
        response.status(422).json({
          error: {code: 'REQUEST_DIGEST_MISMATCH', message: 'request SHA-256 does not match canonical request bytes'},
        });
        return;
      }
      if (
        parsed.expected_model.id !== config.model.id ||
        parsed.expected_model.sha256 !== config.model.sha256
      ) {
        response.status(422).json({
          error: {code: 'MODEL_IDENTITY_MISMATCH', message: 'requested UI model is not installed'},
        });
        return;
      }
      app.locals.activity.active += 1;
      app.locals.activity.lastActivityAt = Date.now();
      try {
        const rendered = RenderResponseSchema.parse(await pipeline(parsed));
        response.status(200).json(rendered);
      } finally {
        app.locals.activity.active -= 1;
        app.locals.activity.lastActivityAt = Date.now();
      }
    } catch (error) {
      next(error);
    }
  });

  app.post('/v1/retention/finalized', async (request, response, next) => {
    try {
      if (config.apiToken) {
        const authorization = request.header('authorization') ?? '';
        const supplied = authorization.startsWith('Bearer ') ? authorization.slice(7) : '';
        if (!secureTokenMatch(supplied, config.apiToken)) {
          response.status(401).json({error: {code: 'UNAUTHORIZED', message: 'render token is invalid'}});
          return;
        }
      }
      const requestSha256 = String(request.body?.request_sha256 ?? '');
      const finalVideoSha256 = String(request.body?.final_video_sha256 ?? '');
      if (!sha256.test(requestSha256) || !sha256.test(finalVideoSha256)) {
        response.status(422).json({error: {code: 'RETENTION_REQUEST_INVALID', message: 'retention requires SHA-256 bindings'}});
        return;
      }
      const receipt = await retention.markFinalized({requestSha256, finalVideoSha256});
      if (typeof retention.sweep === 'function') {
        app.locals.activity.pendingRetention += 1;
        const delay = Math.max(0, receipt.purge_after_ms - Date.now());
        setTimeout(async () => {
          try {
            await retention.sweep?.(Date.now());
          } finally {
            app.locals.activity.pendingRetention -= 1;
          }
        }, delay);
      }
      response.status(202).json(receipt);
    } catch (error) {
      next(error);
    }
  });

  app.use((error: unknown, _request: Request, response: Response, _next: NextFunction) => {
    if (error instanceof ZodError) {
      response.status(422).json({error: {code: 'REQUEST_INVALID', message: error.message}});
      return;
    }
    if (error instanceof RenderPipelineError) {
      response.status(422).json({error: {code: error.code, message: error.message}});
      return;
    }
    const message = error instanceof Error ? error.message : 'unknown render failure';
    response.status(500).json({error: {code: 'RENDER_FAILED', message}});
  });
  return app;
};

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const config = loadConfig();
  const app = createApp(config);
  const server = app.listen(config.port, config.host);
  if (config.idleTimeoutSeconds > 0) {
    const timer = setInterval(() => {
      const activity = app.locals.activity as {active: number; lastActivityAt: number; pendingRetention: number};
      if (
        activity.active === 0 &&
        activity.pendingRetention === 0 &&
        Date.now() - activity.lastActivityAt >= config.idleTimeoutSeconds * 1000
      ) {
        clearInterval(timer);
        server.close(() => process.exit(0));
      }
    }, 1000);
    timer.unref();
  }
}
