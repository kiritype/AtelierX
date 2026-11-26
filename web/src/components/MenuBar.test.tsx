// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import MenuBar, { MenuButton, type MenuEntry } from './MenuBar';

const mounted: { root: Root; host: HTMLDivElement }[] = [];

afterEach(async () => {
  for (const { root, host } of mounted.splice(0)) {
    await act(async () => root.unmount());
    host.remove();
  }
});

async function render(content: React.ReactNode) {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(content));
  return host;
}

async function press(key: string) {
  await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })));
}

it('moves between work menus, skips unavailable entries and restores focus on Escape', async () => {
  const run = vi.fn();
  const host = await render(<MenuBar menus={[
    { label: 'Work', items: [{ label: 'Open', run }] },
    { label: 'Image', items: [{ heading: 'Create' }, { label: 'Single', run }, null, { label: 'Unavailable', run, disabled: true }, { label: 'Queue', run }] },
  ]} />);
  const [work, image] = host.querySelectorAll<HTMLButtonElement>('.menu-title');
  expect(work.tabIndex).toBe(0);
  expect(image.tabIndex).toBe(-1);
  await act(async () => work.focus());
  await press('ArrowRight');
  expect(document.activeElement).toBe(image);
  await press('ArrowUp');
  expect(image.getAttribute('aria-expanded')).toBe('true');
  expect(document.activeElement?.textContent).toBe('Queue');
  await press('ArrowUp');
  expect(document.activeElement?.textContent).toBe('Single');
  await press('End');
  expect(document.activeElement?.textContent).toBe('Queue');
  await press('Home');
  expect(document.activeElement?.textContent).toBe('Single');
  await press('ArrowLeft');
  expect(work.getAttribute('aria-expanded')).toBe('true');
  expect(document.activeElement?.textContent).toBe('Open');
  await press('Escape');
  expect(host.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(work);
  expect(run).not.toHaveBeenCalled();
});

it('keeps pointer switching, command activation and dismissal outside the menu', async () => {
  const open = vi.fn();
  const renderImage = vi.fn();
  const host = await render(<MenuBar menus={[
    { label: 'Work', items: [{ label: 'Open', run: open }] },
    { label: 'Image', items: [{ label: 'Render', run: renderImage }] },
  ]} />);
  const [work, image] = host.querySelectorAll<HTMLButtonElement>('.menu-title');
  await act(async () => work.click());
  expect(document.activeElement?.textContent).toBe('Open');
  await act(async () => work.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: image })));
  expect(image.getAttribute('aria-expanded')).toBe('true');
  expect(document.activeElement?.textContent).toBe('Render');
  await act(async () => (document.activeElement as HTMLButtonElement).click());
  expect(renderImage).toHaveBeenCalledOnce();
  expect(open).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(image);
  await act(async () => work.click());
  await act(async () => document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  expect(host.querySelector('[role="menu"]')).toBeNull();
});

it('lets focus leave an open toolbar menu without running a command', async () => {
  const run = vi.fn();
  const items: MenuEntry[] = [{ label: 'Action', run }];
  const host = await render(<><MenuButton label="Tools" items={items} /><button type="button">Next</button></>);
  const [trigger, next] = host.querySelectorAll<HTMLButtonElement>('button');
  await act(async () => trigger.focus());
  await press('ArrowDown');
  expect(document.activeElement?.textContent).toBe('Action');
  expect(trigger.tabIndex).toBe(-1);
  await act(async () => next.focus());
  expect(trigger.getAttribute('aria-expanded')).toBe('false');
  expect(trigger.tabIndex).toBe(0);
  expect(document.activeElement).toBe(next);
  expect(run).not.toHaveBeenCalled();
});
