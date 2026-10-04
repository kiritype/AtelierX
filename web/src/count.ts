// Same rule as the server (core/count.py): the platform preset's `count` decides the unit.
const HANGUL = /[\uac00-\ud7a3\u3131-\u318e]/g;

export function measure(text: string, mode: string | undefined): { amount: number; unit: 'bytes' | 'chars' | 'tokens'; estimated: boolean } {
  if (mode === 'chars') return { amount: [...text].length, unit: 'chars', estimated: false };
  if (mode?.startsWith('tokens')) {
    const hangul = (text.match(HANGUL) ?? []).length;
    return { amount: hangul + Math.ceil(([...text].length - hangul) / 4), unit: 'tokens', estimated: true };
  }
  return { amount: new TextEncoder().encode(text).length, unit: 'bytes', estimated: false };
}
