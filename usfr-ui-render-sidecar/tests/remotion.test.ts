import {describe, expect, it} from 'vitest';

import {renderFixture} from './render-fixture';

describe('Remotion UI replica', () => {
  it('renders exact Chinese Arabic Portuguese and English text', async () => {
    const result = await renderFixture(['立即购买', 'اشتر الآن', 'Comprar agora', 'Buy now']);
    try {
      expect(result.probe.codec_name).toBe('h264');
      expect(result.replacementGlyphCount).toBe(0);
      expect(result.receipt.rendered_text).toEqual([
        '立即购买',
        'اشتر الآن',
        'Comprar agora',
        'Buy now',
      ]);
    } finally {
      await result.cleanup();
    }
  });

  it('keeps frame count and viewport fixed', async () => {
    const result = await renderFixture(['Buy now'], {frames: 18, width: 180, height: 320});
    try {
      expect(Number(result.probe.nb_read_frames)).toBe(18);
      expect([result.probe.width, result.probe.height]).toEqual([180, 320]);
    } finally {
      await result.cleanup();
    }
  });
});
