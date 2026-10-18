import { expect, test } from 'vitest';
import { nameIdHint, nameLabel } from './nameLabels';

test('uses a name alone until another item has that name', () => {
  const items = [
    { id: '12345678-0000-4000-8000-000000000001', name: '빛' },
    { id: '87654321-0000-4000-8000-000000000002', name: '그림자' },
  ];
  expect(nameLabel(items[0], items)).toBe('빛');
  expect(nameIdHint(items[0], items)).toBeNull();
  expect(nameLabel({ id: 'missing', name: '' }, items)).toBe('missing');
});

test('extends a short ID hint until same-named items are distinct', () => {
  const items = [
    { id: '12345678-0000-4000-8000-000000000001', name: '빛' },
    { id: '12345678-1000-4000-8000-000000000002', name: '빛' },
  ];
  expect(nameIdHint(items[0], items)).toBe('12345678-0');
  expect(nameIdHint(items[1], items)).toBe('12345678-1');
  expect(nameLabel(items[0], items)).toBe('빛 (12345678-0)');
});
