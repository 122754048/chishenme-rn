import {access} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';

import type {UiReplicaProps} from './UiReplica';

export type {UiReplicaProps} from './UiReplica';

let serveUrlPromise: Promise<string> | undefined;

// A fixed small worker count keeps CPU-only renders responsive without oversubscribing the host.
export const FAST_RENDER_CONCURRENCY = 2;

const entryPoint = fileURLToPath(new URL('./index.tsx', import.meta.url));

const bundledServeUrl = (): Promise<string> => {
  if (!serveUrlPromise) {
    serveUrlPromise = bundle({
      entryPoint,
      onProgress: () => undefined,
    });
  }
  return serveUrlPromise;
};

const browserExecutable = async (): Promise<string | undefined> => {
  const candidates = [
    process.env.USFR_UI_CHROME_EXECUTABLE,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  ].filter((value): value is string => Boolean(value));
  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  return undefined;
};

export const renderReplica = async (props: UiReplicaProps, outputPath: string) => {
  const serveUrl = await bundledServeUrl();
  const composition = await selectComposition({
    serveUrl,
    id: 'UiReplica',
    inputProps: props,
    browserExecutable: await browserExecutable(),
    chromiumOptions: {gl: 'swiftshader'},
  });
  await renderMedia({
    serveUrl,
    composition,
    codec: 'h264',
    outputLocation: outputPath,
    inputProps: props,
    browserExecutable: await browserExecutable(),
    chromiumOptions: {gl: 'swiftshader'},
    concurrency: FAST_RENDER_CONCURRENCY,
    offthreadVideoThreads: 1,
    logLevel: 'warn',
  });
  return {
    output_path: outputPath,
    rendered_text: props.states.flatMap((state) => state.expected_text),
    state_sequence: props.states.map((state) => state.state_id),
    cpu_only: true,
  };
};
