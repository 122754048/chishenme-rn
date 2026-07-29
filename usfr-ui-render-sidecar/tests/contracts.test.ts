import {describe, expect, it} from 'vitest';

import {RenderRequestSchema} from '../src/contracts';
import {canonicalSha256} from '../src/digests';
import {validRequest} from './fixtures';

describe('render request contract', () => {
  it('accepts exact UTF-8 truth and a bound motion reference', () => {
    const request = RenderRequestSchema.parse(validRequest(['立即购买', 'مرحبا']));

    expect(request.motion_reference.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(request.ui_truth_card.approved_copy).toEqual(['立即购买', 'مرحبا']);
  });

  it('rejects replacement glyphs and question-mark placeholder runs', () => {
    expect(() => RenderRequestSchema.parse(validRequest(['????']))).toThrow();
    expect(() => RenderRequestSchema.parse(validRequest(['bad\uFFFDtext']))).toThrow();
  });

  it('rejects a motion contract that differs from the render contract', () => {
    const request = validRequest();
    request.motion_reference.source_ui_interaction_contract.region_id = 'ui-002';

    expect(() => RenderRequestSchema.parse(request)).toThrow(/motion reference contract/i);
  });

  it('hashes canonical Unicode JSON without ASCII escaping', () => {
    expect(canonicalSha256({text: '中文'})).toBe(
      canonicalSha256(JSON.parse('{"text":"中文"}')),
    );
    expect(canonicalSha256({text: '中文'})).toHaveLength(64);
  });
});
