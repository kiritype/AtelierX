import { describe, expect, it } from 'vitest';
import { pixaiVersionId } from './pixai';

describe('PixAI LoRA addresses', () => {
  it('takes the version id from a Model Market address', () => {
    expect(pixaiVersionId('https://pixai.art/model/1700000000000000001/1700000000000000002')).toBe('1700000000000000002');
    expect(pixaiVersionId('pixai.art/en/model/1700000000000000001/1700000000000000002?utm=x')).toBe('1700000000000000002');
    expect(pixaiVersionId(' 1700000000000000002 ')).toBe('1700000000000000002');
  });

  it('refuses an address without a version, or anything else', () => {
    expect(pixaiVersionId('https://pixai.art/model/1700000000000000001')).toBeNull();
    expect(pixaiVersionId('https://example.com/model/1/2')).toBeNull();
    expect(pixaiVersionId('lora')).toBeNull();
  });
});
