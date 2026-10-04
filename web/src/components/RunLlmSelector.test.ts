import { describe, expect, it } from 'vitest';
import { effectiveRunLlm, type LlmOverride } from './RunLlmSelector';

const providers = {
  providers: {
    local: { name: 'Local', default_model: 'local-model' },
    remote: { name: 'Remote', default_model: 'remote-model' },
  },
  tasks: { compression: { provider: 'local', model: 'task-model' } },
};

describe('effectiveRunLlm', () => {
  it('shows the configured task provider and model by default', () => {
    expect(effectiveRunLlm('compression', undefined, providers)).toEqual({
      providerId: 'local', providerName: 'Local', model: 'task-model',
    });
  });

  it('uses the selected provider default when its per-run model is blank', () => {
    const override: LlmOverride = { provider: 'remote', model: '' };
    expect(effectiveRunLlm('compression', override, providers)).toEqual({
      providerId: 'remote', providerName: 'Remote', model: 'remote-model',
    });
  });

  it('uses a per-run model while preserving the task provider', () => {
    expect(effectiveRunLlm('compression', { model: 'one-off' }, providers)).toEqual({
      providerId: 'local', providerName: 'Local', model: 'one-off',
    });
  });
});
