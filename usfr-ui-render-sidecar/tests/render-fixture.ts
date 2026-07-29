import {createServer} from 'node:http';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';

import {renderReplica, type UiReplicaProps} from '../src/remotion/render';

const ffmpeg = (args: string[]) => {
  const result = spawnSync('ffmpeg', args, {encoding: 'utf8'});
  if (result.status !== 0) {
    throw new Error(result.stderr || 'FFmpeg failed');
  }
};

const ffprobe = (path: string) => {
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
    throw new Error(result.stderr || 'FFprobe failed');
  }
  return JSON.parse(result.stdout).streams[0] as {
    codec_name: string;
    width: number;
    height: number;
    nb_read_frames: string;
  };
};

export const renderFixture = async (
  copy: string[],
  options: {frames?: number; width?: number; height?: number; fps?: number} = {},
) => {
  const frames = options.frames ?? 18;
  const width = options.width ?? 180;
  const height = options.height ?? 320;
  const fps = options.fps ?? 12;
  const workDir = await mkdtemp(join(tmpdir(), 'usfr-remotion-test-'));
  const motionPath = join(workDir, 'motion.mp4');
  const outputPath = join(workDir, 'output.mp4');
  ffmpeg([
    '-y',
    '-loglevel',
    'error',
    '-f',
    'lavfi',
    '-i',
    `color=c=0x1d2330:s=${width}x${height}:r=${fps}:d=${frames / fps}`,
    '-vf',
    `drawbox=x=20+20*t:y=70:w=80:h=110:color=0x28c987:t=fill`,
    '-frames:v',
    String(frames),
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    motionPath,
  ]);

  const motionBytes = await readFile(motionPath);
  const server = createServer((request, response) => {
    if (request.url !== '/motion.mp4') {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, {
      'Content-Type': 'video/mp4',
      'Content-Length': motionBytes.length,
    });
    response.end(motionBytes);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('fixture server has no TCP address');
  }

  const props: UiReplicaProps = {
    motionVideoUrl: `http://127.0.0.1:${address.port}/motion.mp4`,
    width,
    height,
    fps,
    durationInFrames: frames,
    transitionShell: {entry: {type: 'hard_cut'}, exit: {type: 'hard_cut'}},
    states: [
      {
        state_id: 'state-001',
        frame_ms: 0,
        expected_text: copy,
        expected_layout: copy.map((text, index) => ({
          element_id: `copy-${index + 1}`,
          role: 'label',
          text,
          bbox: [12, 12 + index * 44, width - 12, 48 + index * 44],
          font_size: 16,
          color: '#ffffff',
          background_color: '#111827',
          text_align: 'center' as const,
        })),
      },
    ],
  };

  try {
    const receipt = await renderReplica(props, outputPath);
    return {
      receipt,
      probe: ffprobe(outputPath),
      outputPath,
      replacementGlyphCount: copy.join('').split('\uFFFD').length - 1,
      cleanup: async () => rm(workDir, {recursive: true, force: true}),
    };
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
};
