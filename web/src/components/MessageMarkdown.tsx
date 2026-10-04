import { marked, type Token } from 'marked';
import { Fragment, type ReactNode } from 'react';

// Render tokens as React elements: raw HTML stays text and never enters innerHTML.
export function safeMessageUrl(value: string) {
  return /^(https?:\/\/|mailto:|\/api\/image\/files\/|#)/i.test(value) ? value : undefined;
}

export default function MessageMarkdown({ text, component }: { text: string; component?: (raw: string) => ReactNode }) {
  const render = (tokens: Token[]): ReactNode => tokens.map((token, index) => {
    const t = token as any;
    const children = () => t.tokens ? render(t.tokens) : t.text;
    switch (t.type) {
      case 'space': return null;
      case 'heading': {
        const Tag = `h${t.depth}` as 'h1';
        return <Tag key={index}>{children()}</Tag>;
      }
      case 'paragraph': return <div className="message-paragraph" key={index}>{children()}</div>;
      case 'text': return <span key={index}>{children()}</span>;
      case 'strong': return <strong key={index}>{children()}</strong>;
      case 'em': return <em key={index}>{children()}</em>;
      case 'del': return <del key={index}>{children()}</del>;
      case 'br': return <br key={index} />;
      case 'hr': return <hr key={index} />;
      case 'escape': return <span key={index}>{t.text}</span>;
      case 'code': return <pre key={index}><code>{t.text}</code></pre>;
      case 'codespan': return <code key={index}>{t.text}</code>;
      case 'blockquote': return <blockquote key={index}>{children()}</blockquote>;
      case 'link': return <a key={index} href={safeMessageUrl(t.href)} target="_blank" rel="noopener noreferrer">{children()}</a>;
      case 'image': return safeMessageUrl(t.href) && /^https?:|^\/api\//i.test(t.href)
        ? <img key={index} src={t.href} alt={t.text} loading="lazy" referrerPolicy="no-referrer" /> : <span key={index}>{t.text}</span>;
      case 'html': return <Fragment key={index}>{component?.(t.raw) ?? t.raw}</Fragment>;
      case 'list': {
        const Tag = t.ordered ? 'ol' : 'ul';
        return <Tag key={index} start={t.ordered ? t.start : undefined}>{t.items.map((item: any, n: number) => <li key={n}>{item.task && <input type="checkbox" checked={item.checked} readOnly disabled />}{render(item.tokens)}</li>)}</Tag>;
      }
      case 'table': return <table key={index}><thead><tr>{t.header.map((cell: any, n: number) => <th key={n}>{render(cell.tokens)}</th>)}</tr></thead><tbody>{t.rows.map((row: any[], n: number) => <tr key={n}>{row.map((cell, c) => <td key={c}>{render(cell.tokens)}</td>)}</tr>)}</tbody></table>;
      default: return <span key={index}>{t.raw ?? t.text}</span>;
    }
  });
  return <div className="message-markdown">{render(marked.lexer(text, { breaks: true }))}</div>;
}
