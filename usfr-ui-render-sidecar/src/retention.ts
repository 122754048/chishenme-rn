import {mkdir, readdir, readFile, rm, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const SHA256 = /^[0-9a-f]{64}$/;
const SCHEMA_VERSION = 'usfr-ui-retention/v1';

type RetentionReceipt = {
  schema_version: typeof SCHEMA_VERSION;
  request_sha256: string;
  final_video_sha256: string;
  finalized_at_ms: number;
  purge_after_ms: number;
};

const validSha = (value: string, label: string): string => {
  if (!SHA256.test(value)) {
    throw new Error(`${label} must be a lowercase SHA-256`);
  }
  return value;
};

export class SidecarRetentionStore {
  private readonly jobsRoot: string;
  private readonly retentionMs: number;

  public constructor(options: {runtimeRoot: string; retentionHours: number}) {
    if (!Number.isInteger(options.retentionHours) || options.retentionHours !== 24) {
      throw new Error('UI Sidecar retention must be exactly 24 hours');
    }
    this.jobsRoot = resolve(options.runtimeRoot, 'jobs');
    this.retentionMs = options.retentionHours * 60 * 60 * 1000;
  }

  private jobDirectory(requestSha256: string): string {
    const requestSha = validSha(requestSha256, 'request SHA-256');
    const directory = resolve(this.jobsRoot, requestSha);
    if (!directory.startsWith(`${this.jobsRoot}\\`) && !directory.startsWith(`${this.jobsRoot}/`)) {
      throw new Error('retention job path is invalid');
    }
    return directory;
  }

  public async markFinalized(options: {
    requestSha256: string;
    finalVideoSha256: string;
    finalizedAtMs?: number;
  }): Promise<RetentionReceipt> {
    const finalizedAtMs = options.finalizedAtMs ?? Date.now();
    if (!Number.isSafeInteger(finalizedAtMs) || finalizedAtMs < 0) {
      throw new Error('finalized timestamp is invalid');
    }
    const receipt: RetentionReceipt = {
      schema_version: SCHEMA_VERSION,
      request_sha256: validSha(options.requestSha256, 'request SHA-256'),
      final_video_sha256: validSha(options.finalVideoSha256, 'final video SHA-256'),
      finalized_at_ms: finalizedAtMs,
      purge_after_ms: finalizedAtMs + this.retentionMs,
    };
    const directory = this.jobDirectory(receipt.request_sha256);
    await mkdir(directory, {recursive: true});
    await writeFile(joinRetentionPath(directory), JSON.stringify(receipt), 'utf8');
    return receipt;
  }

  public async sweep(nowMs = Date.now()): Promise<string[]> {
    if (!Number.isSafeInteger(nowMs) || nowMs < 0) {
      throw new Error('sweep timestamp is invalid');
    }
    let entries;
    try {
      entries = await readdir(this.jobsRoot, {withFileTypes: true});
    } catch (error: unknown) {
      if ((error as {code?: string}).code === 'ENOENT') {
        return [];
      }
      throw error;
    }
    const deleted: string[] = [];
    for (const entry of entries) {
      if (!entry.isDirectory() || !SHA256.test(entry.name)) {
        continue;
      }
      const directory = this.jobDirectory(entry.name);
      let receipt: RetentionReceipt;
      try {
        receipt = JSON.parse(await readFile(joinRetentionPath(directory), 'utf8')) as RetentionReceipt;
      } catch {
        continue;
      }
      if (
        receipt.schema_version !== SCHEMA_VERSION ||
        receipt.request_sha256 !== entry.name ||
        !SHA256.test(receipt.final_video_sha256) ||
        !Number.isSafeInteger(receipt.purge_after_ms) ||
        receipt.purge_after_ms > nowMs
      ) {
        continue;
      }
      await rm(directory, {recursive: true, force: true, maxRetries: 2, retryDelay: 100});
      deleted.push(entry.name);
    }
    return deleted;
  }
}

const joinRetentionPath = (directory: string): string => resolve(directory, 'retention.json');
