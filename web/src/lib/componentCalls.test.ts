import { describe, expect, it } from 'vitest';
import { findCalls, readValue, splitReply } from './componentCalls';

const CALL = `<Asset c='C001' o='001' e='010' bg='002' n='2' data='{"hp": 3,}' />`;

describe('component calls', () => {
  it('keeps values as written for text platforms', () => {
    const [call] = findCalls(CALL, ['Asset'], { attribute_format: 'text' });
    expect(call.attrs).toEqual({ c: 'C001', o: '001', e: '010', bg: '002', n: '2', data: '{"hp": 3,}' });
    expect(call.errors).toEqual([]);
  });

  it('reads JSON leniently and keeps plain words (the default)', () => {
    const [call] = findCalls(CALL, ['Asset']);
    expect(call.attrs).toEqual({ c: 'C001', o: '001', e: '010', bg: '002', n: 2, data: { hp: 3 } });
    expect(readValue('{broken').error).toBeTruthy();
  });

  it('refuses plain words under strict JSON', () => {
    const [call] = findCalls(CALL, ['Asset'], { attribute_format: 'json' });
    expect(call.errors.map((e) => e.split(':')[0])).toEqual(expect.arrayContaining(['c', 'o', 'data']));
  });

  it('finds every call of the named components in a reply, in order', () => {
    const reply = `앞 문장 <Asset c='C001' /> 중간 <Other x='1' /> <Asset c='C002' /> 끝`;
    expect(findCalls(reply, ['Asset']).map((c) => c.attrs.c)).toEqual(['C001', 'C002']);
    const parts = splitReply(reply, ['Asset'], { attribute_format: 'text', decode: [] });
    expect(parts.filter((p) => 'component' in p)).toHaveLength(2);
    expect(parts.map((p) => ('text' in p ? p.text : p.raw)).join('')).toBe(reply);
  });

  it('applies the decode table first', () => {
    const [call] = findCalls('[[Asset c=&apos;C001&apos; />', ['Asset'], { attribute_format: 'text', decode: [['&apos;', "'"], { from: '[[', to: '<' }] });
    expect(call.attrs).toEqual({ c: 'C001' });
  });
});
