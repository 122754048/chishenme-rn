import {createHash} from 'node:crypto';
import {readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

import {canonicalSha256} from '../src/digests';

const FILE_GROUPS = {
  renderer: [
    'src/render-pipeline.ts',
    'src/retention.ts',
    'src/python-runner.ts',
    'src/remotion/render.ts',
    'src/server.ts',
  ],
  extractor: ['python/track_extractor.py', 'python/requirements.lock'],
  composition: ['src/remotion/index.tsx', 'src/remotion/UiReplica.tsx', 'src/fonts.ts'],
  contract: ['src/contracts.ts', 'src/digests.ts'],
} as const;

const hashFiles = async (root: string, relativePaths: readonly string[]): Promise<string> => {
  const hash = createHash('sha256');
  for (const relativePath of relativePaths) {
    hash.update(relativePath, 'utf8');
    hash.update('\0');
    const text = await readFile(path.join(root, relativePath), 'utf8');
    hash.update(text.replace(/\r\n/g, '\n'), 'utf8');
    hash.update('\0');
  }
  return hash.digest('hex');
};

export const buildManifest = async (root: string) => {
  const identity = {
    schema_version: 'usfr-ui-sidecar-manifest/v1' as const,
    model_id: 'usfr-ui-remotion-opencv',
    cpu_only: true as const,
    renderer_sha256: await hashFiles(root, FILE_GROUPS.renderer),
    extractor_sha256: await hashFiles(root, FILE_GROUPS.extractor),
    composition_sha256: await hashFiles(root, FILE_GROUPS.composition),
    contract_sha256: await hashFiles(root, FILE_GROUPS.contract),
  };
  return {...identity, model_sha256: canonicalSha256(identity)};
};

const modulePath = fileURLToPath(import.meta.url);
if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  const root = path.resolve(path.dirname(modulePath), '..');
  const manifest = await buildManifest(root);
  await writeFile(
    path.join(root, 'sidecar-manifest.json'),
    `${JSON.stringify(manifest, null, 2)}\n`,
    'utf8',
  );
}
