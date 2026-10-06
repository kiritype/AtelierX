import { describe, expect, it } from 'vitest';
import { tm } from './i18n';

describe('tm', () => {
  it('translates a server message given as a value of another', () => {
    const text = tm({
      key: 'server.postprocess.cannot_connect_to_comfyui',
      text: 'Cannot connect to ComfyUI: x',
      values: { error: { key: 'server.comfy.cannot_connect_to_comfyui_check_that', text: 'Cannot connect.', values: {} } },
    });
    expect(text).not.toContain('[object Object]');
    expect(text).not.toContain('{error}');
  });

  it('shows what a 402 from an LLM service means, in Korean', () => {
    const text = tm({
      key: 'server.llm.http_error',
      text: 'Ollama Cloud answered 402: Payment or a plan is required.',
      values: { name: 'Ollama Cloud', status: 402, detail: { key: 'server.llm.http_hint.payment', text: 'Payment or a plan is required.', values: {} } },
    });
    expect(text).toContain('Ollama Cloud');
    expect(text).toContain('402');
    expect(text).toContain('요금제');
  });

  it('falls back to the English text of an unknown key', () => {
    expect(tm({ key: 'server.nope', text: 'Plain text' })).toBe('Plain text');
  });
});
