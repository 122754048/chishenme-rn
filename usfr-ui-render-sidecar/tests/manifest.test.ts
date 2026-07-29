import {readFile} from 'node:fs/promises';

import {describe, expect, it} from 'vitest';

import {buildManifest} from '../scripts/build-manifest';
import {canonicalSha256} from '../src/digests';

describe('immutable Sidecar manifest', () => {
  it('matches the exact current extractor renderer and composition bytes', async () => {
    const generated = await buildManifest(process.cwd());
    const stored = JSON.parse(await readFile('sidecar-manifest.json', 'utf8'));

    expect(stored).toEqual(generated);
    const {model_sha256: _modelSha, ...identity} = generated;
    expect(generated.model_sha256).toBe(canonicalSha256(identity));
    expect(generated.cpu_only).toBe(true);
  });
});
