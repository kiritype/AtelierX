import { describe, expect, it } from 'vitest';
import type { PromptSource, SingleRun } from '../imageTypes';
import { cleanPrompt, combineSources, orderedSources, promptSources, replaceSource, restorePromptSources } from './singlePromptSources';

const source = (kind: PromptSource['kind'], positive: string, negative = ''): PromptSource => ({
  kind, id: kind, name: kind, positive, negative,
});

describe('single prompt sources', () => {
  it('cleans only comment syntax and retains escaped hashes and weighted tags', () => {
    expect(cleanPrompt('1girl, (blue eyes:1.2), \\#literal, red hair # note\n  (soft light:0.8)  '))
      .toBe('1girl, (blue eyes:1.2), #literal, red hair\n  (soft light:0.8)');
  });

  it('replaces one material per kind, orders canonically, and refreshes the direct source', () => {
    const initial = [source('style', 'style'), source('common', 'common'), source('character', 'character')];
    const replaced = replaceSource(initial, 'common', source('common', 'updated common'));
    const submitted = promptSources('scene # note', 'blur, \\#literal', replaced);
    expect(orderedSources(submitted).map(item => item.kind)).toEqual(['common', 'direct', 'character', 'style']);
    expect(submitted.filter(item => item.kind === 'common')).toHaveLength(1);
    expect(combineSources(submitted, 'positive')).toBe('updated common, scene, character, style');
    expect(submitted.find(item => item.kind === 'direct')?.negative).toBe('blur, #literal');
  });

  it('restores frozen source text without stripping comments again and safely restores legacy runs', () => {
    const frozen = [source('common', 'soft # saved literal'), source('direct', 'forest, (mist:1.2)', 'blur')];
    const run = { actual: { positive: 'soft # saved literal, forest, (mist:1.2)', negative: 'blur', settings: {}, prompt_sources: frozen } } as SingleRun;
    const restored = restorePromptSources(run);
    expect(restored.positive).toBe('forest, (mist:1.2)');
    expect(restored.sources).toEqual([frozen[0]]);
    expect(combineSources(promptSources(restored.positive, restored.negative, restored.sources), 'positive'))
      .toBe('soft # saved literal, forest, (mist:1.2)');

    const legacy = { actual: { positive: 'literal # restored', negative: 'bad # note', settings: {} } } as SingleRun;
    const old = restorePromptSources(legacy);
    expect(old.sources).toEqual([]);
    expect(old.positive).toBe('literal \\# restored');
    expect(old.negative).toBe('bad \\# note');
    expect(cleanPrompt(old.positive)).toBe('literal # restored');
  });
});
