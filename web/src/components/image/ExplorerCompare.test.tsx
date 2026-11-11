// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ExplorerCompare from './ExplorerCompare';
import type { ExplorerCandidate, ExplorerSession } from '../../styleExplorerTypes';

let host: HTMLDivElement;
let root: Root;

const candidate = (id: string, index: number): ExplorerCandidate => ({
  id,
  index,
  status: 'done',
  image_url: `/${id}.png`,
  positive: `${id} secret recipe`,
  negative: '',
  settings: { model: `${id} hidden model` },
  artists: [],
  seed: index + 1,
  elo: 1200,
  matches: 0,
  wins: 0,
  draws: 0,
  rejected: 0,
});

const session = (pair: ExplorerSession['pair'] = { id: 'pair-1', a: 'a', b: 'b' }): ExplorerSession => ({
  id: 'session',
  name: 'Example',
  service: 'comfyui',
  family: 'anima',
  created_at: '',
  budget: 30,
  used: 0,
  candidate_count: 0,
  vote_count: 0,
  revision: 1,
  config: {} as ExplorerSession['config'],
  candidates: [candidate('a', 0), candidate('b', 1)],
  pair,
  votes: [],
  ranking: [],
});

const render = async (s: ExplorerSession, vote: (result: string) => void, options: { active?: boolean; busy?: boolean } = {}) => {
  await act(async () =>
    root.render(
      <ExplorerCompare session={s} vote={vote} active={options.active} busy={options.busy ?? false} />,
    ),
  );
};

const section = () => host.querySelector('section.explorer-comparator') as HTMLElement;
const press = async (target: EventTarget, key: string, init: KeyboardEventInit = {}) => {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  await act(async () => target.dispatchEvent(event));
  return event;
};

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  document.querySelectorAll('[aria-modal="true"]').forEach((node) => node.remove());
  host.remove();
});

it('maps numeric and legacy shortcuts, including numpad key values, to every vote result', async () => {
  const vote = vi.fn();
  await render(session(), vote);

  for (const [key, code, result] of [
    ['1', 'Digit1', 'a'],
    ['2', 'Digit2', 'b'],
    ['3', 'Digit3', 'tie'],
    ['4', 'Digit4', 'neither'],
    ['5', 'Digit5', 'skip'],
    ['1', 'Numpad1', 'a'],
    ['2', 'Numpad2', 'b'],
    ['3', 'Numpad3', 'tie'],
    ['4', 'Numpad4', 'neither'],
    ['5', 'Numpad5', 'skip'],
    ['a', 'KeyA', 'a'],
    ['b', 'KeyB', 'b'],
    ['t', 'KeyT', 'tie'],
    ['n', 'KeyN', 'neither'],
    ['s', 'KeyS', 'skip'],
  ]) {
    await press(section(), key, { code });
    expect(vote).toHaveBeenLastCalledWith(result);
  }
  expect(vote).toHaveBeenCalledTimes(15);
});

it('shows matching keyboard hints on the vote buttons', async () => {
  await render(session(), vi.fn());
  const buttons = [...host.querySelectorAll('button[aria-keyshortcuts]')];
  expect(buttons.map((button) => button.getAttribute('aria-keyshortcuts'))).toEqual([
    '1 A',
    '2 B',
    '3 T',
    '4 N',
    '5 S',
  ]);
  expect(buttons.map((button) => button.querySelector('kbd')?.textContent)).toEqual(['1', '2', '3', '4', '5']);
});

it('ignores guarded shortcuts and events from outside the comparator', async () => {
  const vote = vi.fn();
  await render(session(), vote);
  const compare = section();

  await press(document, '1');
  await press(host.appendChild(document.createElement('div')), '1');
  await press(compare, '1', { ctrlKey: true });
  await press(compare, '1', { altKey: true });
  await press(compare, '1', { metaKey: true });
  await press(compare, '1', { shiftKey: true });
  await press(compare, '1', { repeat: true });
  await press(compare, '1', { isComposing: true });

  const prevented = new KeyboardEvent('keydown', { key: '1', bubbles: true, cancelable: true });
  prevented.preventDefault();
  await act(async () => compare.dispatchEvent(prevented));

  for (const tag of ['input', 'textarea', 'select']) {
    const control = document.createElement(tag);
    compare.append(control);
    await press(control, '1');
    control.remove();
  }
  const editable = document.createElement('div');
  editable.contentEditable = 'true';
  compare.append(editable);
  await press(editable, '1');
  editable.remove();

  const modal = document.createElement('div');
  modal.setAttribute('aria-modal', 'true');
  document.body.append(modal);
  await press(compare, '1');
  modal.remove();

  expect(vote).not.toHaveBeenCalled();
});

it('blocks shortcuts and buttons while inactive, busy, or either image is broken', async () => {
  const vote = vi.fn();
  await render(session(), vote, { active: false });
  await press(section(), '1');
  expect([...host.querySelectorAll('button[aria-keyshortcuts]')].every((button) => (button as HTMLButtonElement).disabled)).toBe(true);

  await render(session(), vote, { busy: true });
  await press(section(), '1');
  expect([...host.querySelectorAll('button[aria-keyshortcuts]')].every((button) => (button as HTMLButtonElement).disabled)).toBe(true);

  await render(session(), vote);
  await act(async () => host.querySelector('img')!.dispatchEvent(new Event('error')));
  await press(section(), '1');
  expect([...host.querySelectorAll('button[aria-keyshortcuts]')].every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
  expect(vote).not.toHaveBeenCalled();
});

it('keeps focus on the comparator between pairs and hides revealed details for the next pair', async () => {
  const vote = vi.fn();
  const first = session();
  await render(first, vote);
  const compare = section();
  await act(async () => host.querySelector<HTMLButtonElement>('button.ghost')!.click());
  expect(host.textContent).toContain('a hidden model');

  await press(compare, '1');
  expect(vote).toHaveBeenCalledWith('a');
  expect(document.activeElement).toBe(compare);

  await render({ ...first, pair: null }, vote);
  expect(section()).toBe(compare);
  expect(document.activeElement).toBe(compare);

  const next = {
    ...first,
    candidates: [...first.candidates, candidate('c', 2)],
    pair: { id: 'pair-2', a: 'b', b: 'c' },
  };
  await render(next, vote);
  expect(section()).toBe(compare);
  expect(document.activeElement).toBe(compare);
  expect(host.textContent).not.toContain('a hidden model');
  expect(host.querySelector('button.ghost')?.getAttribute('aria-expanded')).toBe('false');
});
