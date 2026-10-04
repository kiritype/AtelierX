export const LLM_PRESETS = [
  { id: 'ollama', name: 'Ollama Cloud', type: 'openai_compatible', base_url: 'https://ollama.com/v1' },
  { id: 'gemini', name: 'Google Gemini API (AI Studio)', type: 'openai_compatible', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai' },
  { id: 'vertex', name: 'Google Vertex AI (OAuth)', type: 'vertex_openai', base_url: '' },
  { id: 'openrouter', name: 'OpenRouter', type: 'openai_compatible', base_url: 'https://openrouter.ai/api/v1' },
  { id: 'deepseek', name: 'DeepSeek', type: 'openai_compatible', base_url: 'https://api.deepseek.com' },
  { id: 'custom', name: 'OpenAI-compatible', type: 'openai_compatible', base_url: '' },
] as const;

export function vertexUrl(project: string, location: string) {
  if (!/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(project) || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(location)) return '';
  const host = location === 'global' ? 'aiplatform.googleapis.com' : `${location}-aiplatform.googleapis.com`;
  return `https://${host}/v1/projects/${project}/locations/${location}/endpoints/openapi`;
}

export function newProvider(presetId: string) {
  const preset = LLM_PRESETS.find(p => p.id === presetId) ?? LLM_PRESETS[5];
  return {
    name: String(preset.name), type: preset.type, base_url: preset.base_url, preset: preset.id,
    ...(preset.id === 'vertex' ? { vertex_project: '', vertex_location: 'global' } : {}),
    key: null, trusted: false, default_model: null, models: {},
  };
}
