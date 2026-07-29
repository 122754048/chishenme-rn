import {spawn} from 'node:child_process';
import {resolve} from 'node:path';

export type PythonExtractorResult = {
  video_path: string;
  track_path: string;
};

export class PythonExtractorError extends Error {
  public readonly code = 'TRACK_EXTRACTION_FAILED';
}

export const runPythonExtractor = async (options: {
  projectRoot: string;
  pythonExecutable: string;
  sourcePath: string;
  targetPath: string;
  contractPath: string;
  outputDir: string;
  timeoutMs: number;
}): Promise<PythonExtractorResult> => {
  const script = resolve(options.projectRoot, 'python', 'track_extractor.py');
  const args = [
    script,
    '--source',
    options.sourcePath,
    '--target',
    options.targetPath,
    '--contract',
    options.contractPath,
    '--output-dir',
    options.outputDir,
  ];
  return new Promise((resolvePromise, reject) => {
    const child = spawn(options.pythonExecutable, args, {
      cwd: options.projectRoot,
      shell: false,
      windowsHide: true,
      env: {...process.env, PYTHONIOENCODING: 'utf-8'},
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill();
      reject(new PythonExtractorError('OpenCV track extraction timed out'));
    }, options.timeoutMs);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
      if (stdout.length > 1024 * 1024) {
        child.kill();
      }
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
      if (stderr.length > 1024 * 1024) {
        child.kill();
      }
    });
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(new PythonExtractorError(`OpenCV process could not start: ${error.message}`));
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      let value: unknown;
      try {
        value = JSON.parse(stdout.trim());
      } catch {
        reject(new PythonExtractorError(`OpenCV process returned malformed UTF-8 JSON: ${stderr.slice(-500)}`));
        return;
      }
      if (
        code !== 0 ||
        typeof value !== 'object' ||
        value === null ||
        (value as {ok?: unknown}).ok !== true ||
        typeof (value as {video_path?: unknown}).video_path !== 'string' ||
        typeof (value as {track_path?: unknown}).track_path !== 'string'
      ) {
        const message =
          typeof value === 'object' && value !== null && typeof (value as {error?: unknown}).error === 'string'
            ? (value as {error: string}).error
            : stderr.slice(-500);
        reject(new PythonExtractorError(`OpenCV track extraction failed: ${message}`));
        return;
      }
      resolvePromise({
        video_path: (value as {video_path: string}).video_path,
        track_path: (value as {track_path: string}).track_path,
      });
    });
  });
};
