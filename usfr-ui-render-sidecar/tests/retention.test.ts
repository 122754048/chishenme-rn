import {mkdir, stat, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {mkdtemp, rm} from 'node:fs/promises';

import {describe, expect, it} from 'vitest';

import {SidecarRetentionStore} from '../src/retention';

describe('Sidecar retention', () => {
  it('deletes only a finalized UI job after its 24 hour retention window', async () => {
    const root = await mkdtemp(join(tmpdir(), 'usfr-retention-test-'));
    try {
      const jobsRoot = join(root, 'jobs');
      const requestSha = 'a'.repeat(64);
      const protectedSha = 'b'.repeat(64);
      await mkdir(join(jobsRoot, requestSha), {recursive: true});
      await mkdir(join(jobsRoot, protectedSha), {recursive: true});
      await writeFile(join(jobsRoot, requestSha, 'output-ui.mp4'), 'temporary-ui');
      await writeFile(join(jobsRoot, protectedSha, 'output-ui.mp4'), 'unfinalized-ui');

      const retention = new SidecarRetentionStore({runtimeRoot: root, retentionHours: 24});
      const receipt = await retention.markFinalized({
        requestSha256: requestSha,
        finalVideoSha256: 'c'.repeat(64),
        finalizedAtMs: 1_000,
      });

      expect(receipt.purge_after_ms).toBe(86_401_000);
      expect(await retention.sweep(86_400_999)).toEqual([]);
      expect(await retention.sweep(86_401_000)).toEqual([requestSha]);
      await expect(stat(join(jobsRoot, requestSha))).rejects.toThrow();
      await expect(stat(join(jobsRoot, protectedSha))).resolves.toBeDefined();
    } finally {
      await rm(root, {recursive: true, force: true});
    }
  });
});
