// Rule-based prompt syntax conversion between NovelAI, Anima and SDXL (see promptConvert.js).
export type Profile = 'nai' | 'anima' | 'sdxl';
export const PROFILES: Profile[];
export type Conversion = {
  positive: string;
  negative: string;
  changes: { field: 'positive' | 'negative'; before: string; after: string }[];
  warnings: { field: 'positive' | 'negative'; code: string; text: string }[];
  engine: string;
  version: number;
};
export function convertPrompts(input: { positive?: string; negative?: string; source: Profile; target: Profile; artists?: string[] }): Conversion;
