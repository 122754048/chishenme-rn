import {resolve} from 'node:path';

export type SidecarModel = {id: string; sha256: string};

export type SidecarConfig = {
  host: string;
  port: number;
  apiToken?: string;
  idleTimeoutSeconds: number;
  maxRequestBytes: number;
  model: SidecarModel;
  pythonExecutable: string;
  projectRoot: string;
  runtimeRoot?: string;
  renderTimeoutMs?: number;
};

const positiveInteger = (value: string | undefined, fallback: number, label: string): number => {
  const parsed = value === undefined || value === '' ? fallback : Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer`);
  }
  return parsed;
};

const nonNegativeInteger = (value: string | undefined, fallback: number, label: string): number => {
  const parsed = value === undefined || value === '' ? fallback : Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${label} must be a non-negative integer`);
  }
  return parsed;
};

export const loadConfig = (environment: NodeJS.ProcessEnv = process.env): SidecarConfig => {
  const projectRoot = resolve(environment.USFR_UI_SIDECAR_PROJECT_DIR ?? process.cwd());
  const modelId = environment.USFR_UI_RENDER_MODEL_ID?.trim();
  const modelSha256 = environment.USFR_UI_RENDER_MODEL_SHA256?.trim();
  if (!modelId) {
    throw new Error('USFR_UI_RENDER_MODEL_ID is required');
  }
  if (!modelSha256 || !/^[0-9a-f]{64}$/.test(modelSha256)) {
    throw new Error('USFR_UI_RENDER_MODEL_SHA256 must be a lowercase SHA-256');
  }
  return {
    host: environment.USFR_UI_SIDECAR_HOST?.trim() || '127.0.0.1',
    port: positiveInteger(environment.USFR_UI_SIDECAR_PORT, 47821, 'USFR_UI_SIDECAR_PORT'),
    apiToken: environment.USFR_UI_RENDER_API_TOKEN?.trim() || undefined,
    idleTimeoutSeconds: nonNegativeInteger(
      environment.USFR_UI_SIDECAR_IDLE_TIMEOUT_SECONDS,
      120,
      'USFR_UI_SIDECAR_IDLE_TIMEOUT_SECONDS',
    ),
    maxRequestBytes: positiveInteger(
      environment.USFR_UI_SIDECAR_MAX_REQUEST_BYTES,
      160 * 1024 * 1024,
      'USFR_UI_SIDECAR_MAX_REQUEST_BYTES',
    ),
    model: {id: modelId, sha256: modelSha256},
    pythonExecutable:
      environment.USFR_UI_SIDECAR_PYTHON?.trim() ||
      resolve(projectRoot, '.venv', 'Scripts', 'python.exe'),
    projectRoot,
    runtimeRoot: resolve(projectRoot, '.runtime'),
    renderTimeoutMs: positiveInteger(
      environment.USFR_UI_SIDECAR_RENDER_TIMEOUT_MS,
      300_000,
      'USFR_UI_SIDECAR_RENDER_TIMEOUT_MS',
    ),
  };
};
