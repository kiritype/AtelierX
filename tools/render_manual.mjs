// Render the same Markdown used by VitePress as file://-friendly HTML.
import { marked } from '../web/node_modules/marked/lib/marked.esm.js';
import { readFile, readdir, mkdir, writeFile } from 'node:fs/promises';
import { resolve, relative, dirname } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const source = resolve(root, 'docs/manual');
const output = resolve(process.argv[2]);
const order = ['getting-started', 'walkthrough', 'editing', 'ai-tools', 'chat-test', 'connections', 'image-setup', 'character-images', 'generation', 'gallery-export', 'lora', 'platforms', 'maintenance', 'release-status'];
const guides = (await readdir(resolve(source, 'guide'))).filter(f => f.endsWith('.md')).sort((a, b) => order.indexOf(a.slice(0, -3)) - order.indexOf(b.slice(0, -3)));
const esc = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const pages = await Promise.all(['index.md', ...guides.map(f => `guide/${f}`)].map(async file => {
  const md = await readFile(resolve(source, file), 'utf8');
  return { file, md, title: md.match(/^# (.+)$/m)?.[1] ?? file, url: file.replace(/\.md$/, '.html') };
}));
for (let n = 0; n < pages.length; n++) {
  const page = pages[n];
  const prefix = page.file.includes('/') ? '../' : '';
  const link = p => prefix + p.url;
  let body = marked.parse(page.md).replace(/href="([^"#:]+)\.md(#[^"]*)?"/g, 'href="$1.html$2"');
  const headings = [];
  body = body.replace(/<h([1-6])>(.*?)<\/h\1>/g, (_, level, text) => {
    const id = `section-${headings.length}`;
    headings.push({ id, text: text.replace(/<[^>]+>/g, ''), level });
    return `<h${level} id="${id}">${text}</h${level}>`;
  });
  const nav = pages.map(p => `<a href="${link(p)}"${p === page ? ' aria-current="page"' : ''}>${esc(p.title)}</a>`).join('');
  const toc = headings.filter(h => h.level === '2').map(h => `<a href="#${h.id}">${h.text}</a>`).join(' · ');
  const prev = pages[n - 1], next = pages[n + 1];
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(page.title)} · AtelierX</title><link rel="stylesheet" href="${prefix}manual.css"></head><body>
<a class="skip-link" href="#main">본문으로 건너뛰기</a><header class="topbar"><a class="brand" href="${prefix}index.html">AtelierX <span>사용 설명서</span></a><button class="nav-toggle" aria-controls="sidebar" aria-expanded="false">목차</button><label class="search-wrap">검색 <input type="search" aria-label="설명서 검색"></label></header>
<div class="layout"><aside class="sidebar" id="sidebar"><nav aria-label="전체 목차">${nav}</nav></aside><main id="main"><div id="search-results" aria-live="polite"></div><article class="manual-section"><nav aria-label="이 페이지">${toc}</nav>${body}</article><footer class="page-footer">${prev ? `<a href="${link(prev)}">← ${esc(prev.title)}</a>` : ''} ${next ? `<a href="${link(next)}">${esc(next.title)} →</a>` : ''}<p>AtelierX 0.0.1 · 오프라인 설명서</p></footer></main></div>
<script src="${prefix}search-data.js"></script><script src="${prefix}offline.js"></script></body></html>`;
  await mkdir(dirname(resolve(output, page.url)), { recursive: true });
  await writeFile(resolve(output, page.url), html);
}
await writeFile(resolve(output, 'search-data.js'), `window.manualPages=${JSON.stringify(pages.map(p => ({ title: p.title, url: p.url, text: p.md }))).replaceAll('<', '\\u003c')};`);
console.log(`Rendered ${pages.length} pages to ${relative(root, output)}`);
