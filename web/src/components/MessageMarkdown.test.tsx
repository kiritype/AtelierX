import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import MessageMarkdown, { safeMessageUrl } from './MessageMarkdown';
import { splitReply } from '../lib/componentCalls';

describe('MessageMarkdown', () => {
  it('renders Markdown structure and escaped raw HTML as text', () => {
    const html = renderToStaticMarkup(
      createElement(MessageMarkdown, { text: '**bold**\n\n<script>alert(1)</script>' }),
    );
    expect(html).toContain('<strong><span>bold</span></strong>');
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>');
  });

  it('keeps event handler attributes and script links as text (the document preview uses this renderer)', () => {
    const html = renderToStaticMarkup(
      createElement(MessageMarkdown, { text: 'before\n\n<img src="x" onerror="alert(1)">\n\n[x](javascript:alert(1))' }),
    );
    expect(html).not.toContain('<img');
    expect(html).toContain('onerror=&quot;alert(1)&quot;');
    expect(html).not.toContain('href="javascript');
  });

  it('does not render or call the component handler for fenced or inline code', () => {
    const component = vi.fn(() => createElement('b', null, 'rendered component'));
    const html = renderToStaticMarkup(
      createElement(MessageMarkdown, {
        text: '`<Badge value="inline" />`\n\n```jsx\n<Badge value="fenced" />\n```',
        component,
      }),
    );
    expect(component).not.toHaveBeenCalled();
    expect(html).toContain('&lt;Badge value=&quot;inline&quot; /&gt;');
    expect(html).toContain('&lt;Badge value=&quot;fenced&quot; /&gt;');
    expect(html).not.toContain('rendered component');
  });

  it('hands executable JSX tokens to the component renderer outside code', () => {
    const component = vi.fn((raw: string) => createElement('b', null, `rendered ${raw.trim()}`));
    const html = renderToStaticMarkup(
      createElement(MessageMarkdown, { text: '<Badge value="ok" />', component }),
    );
    expect(component).toHaveBeenCalledTimes(1);
    expect(html).toContain('<b>rendered &lt;Badge value=&quot;ok&quot; /&gt;</b>');
  });

  it('passes a complete HTML block to the renderer when it contains repeated component calls', () => {
    const component = vi.fn((_raw: string) => createElement('b', null, 'rendered'));
    renderToStaticMarkup(createElement(MessageMarkdown, {
      text: '<Badge value="one" />\n<Badge value="two" />', component,
    }));
    expect(component).toHaveBeenCalledTimes(1);
    expect(component.mock.calls[0][0]).toContain('<Badge value="two" />');
    expect(splitReply(component.mock.calls[0][0].trim(), ['Badge']).filter((part) => 'component' in part)).toHaveLength(2);
  });

  it('splits multiple component calls in one reply segment', () => {
    const segments = splitReply('<Badge value="one" /> and <Badge value="two" />', ['Badge']);
    expect(segments.filter((segment) => 'component' in segment)).toHaveLength(2);
    expect(segments.map((segment) => 'component' in segment ? segment.attrs.value : segment.text)).toEqual([
      'one', ' and ', 'two',
    ]);
  });

  it('rejects javascript and other unsafe link targets', () => {
    expect(safeMessageUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeMessageUrl('data:text/html,hello')).toBeUndefined();
    expect(safeMessageUrl('https://example.com')).toBe('https://example.com');
    const html = renderToStaticMarkup(createElement(MessageMarkdown, {
      text: '[unsafe](javascript:alert%281%29) [safe](https://example.com)',
    }));
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain('href="https://example.com"');
  });
});
