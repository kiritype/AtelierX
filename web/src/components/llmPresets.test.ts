import { describe, expect, it } from 'vitest';
import { LLM_PRESETS, newProvider, vertexUrl } from './llmPresets';

describe('external connection presets', () => {
  it('requires user credentials and model choices without implicitly trusting an external service', () => {
    for (const preset of LLM_PRESETS) {
      const provider = newProvider(preset.id);
      expect(provider.trusted).toBe(false);
      expect(provider.key).toBeNull();
      expect(provider.default_model).toBeNull();
    }
  });
  it('keeps independent connections editable without mutating preset defaults', () => {
    const first = newProvider('ollama');
    first.name = 'Edited';
    expect(newProvider('ollama').name).toBe('Ollama Cloud');
    expect(newProvider('gemini').base_url).toContain('/v1beta/openai');
    expect(newProvider('vertex').vertex_location).toBe('global');
  });
  it('uses distinct global and regional Vertex hosts and rejects path or host injection', () => {
    expect(vertexUrl('my-project-123', 'global')).toBe('https://aiplatform.googleapis.com/v1/projects/my-project-123/locations/global/endpoints/openapi');
    expect(vertexUrl('my-project-123', 'us-central1')).toBe('https://us-central1-aiplatform.googleapis.com/v1/projects/my-project-123/locations/us-central1/endpoints/openapi');
    expect(vertexUrl('my-project/other', 'global')).toBe('');
    expect(vertexUrl('my-project-123', 'evil.test/')).toBe('');
    expect(vertexUrl('', 'global')).toBe('');
  });
});
