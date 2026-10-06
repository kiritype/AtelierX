import { describe, expect, it } from 'vitest';
import { placeTip, splitShortcut } from './tooltip';

describe('tooltips', () => {
  it('shows a shortcut apart from the label', () => {
    expect(splitShortcut('잠금 (Ctrl+Shift+L)')).toEqual({ label: '잠금', keys: 'Ctrl+Shift+L' });
    expect(splitShortcut('설정')).toEqual({ label: '설정', keys: null });
    expect(splitShortcut('메모 (2개)')).toEqual({ label: '메모 (2개)', keys: null });
  });

  it('stays inside the window', () => {
    const view = { width: 1000, height: 600 };
    const size = { width: 120, height: 24 };
    // Centred below a button in the middle.
    expect(placeTip({ left: 480, top: 10, right: 520, bottom: 40 }, size, view)).toEqual({ left: 440, top: 46 });
    // Pushed left at the right edge (the top-right buttons).
    expect(placeTip({ left: 960, top: 10, right: 992, bottom: 40 }, size, view).left).toBe(872);
    // Above when there is no room below.
    expect(placeTip({ left: 480, top: 560, right: 520, bottom: 590 }, size, view).top).toBe(530);
  });
});
