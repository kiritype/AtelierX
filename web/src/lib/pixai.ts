// PixAI LoRAs are registered from their Model Market address (#43): pixai.art/model/<model id>/<version id>. The
// version id is what a generation request names; a bare id is accepted too.

export type PixAILora = { id: string; name: string; weight: number; trigger_words: string };

export function pixaiVersionId(text: string): string | null {
  const value = text.trim();
  if (/^\d{6,25}$/.test(value)) return value;
  const m = /pixai\.art\/(?:[a-z]{2}(?:-[A-Za-z]{2})?\/)?model\/(\d{6,25})(?:\/(\d{6,25}))?/.exec(value);
  if (!m) return null;
  // A model page without a version names the model, not a version; PixAI needs the version.
  return m[2] ?? null;
}
