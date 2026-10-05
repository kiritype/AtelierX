// Render the same Markdown used by VitePress as file://-friendly HTML.
import { marked } from '../web/node_modules/marked/lib/marked.esm.js';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { resolve, relative, dirname } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const source = resolve(root, 'docs/manual');
const output = resolve(process.argv[2]);
// Page order is shared with the web manual (docs/manual/.vitepress/config.mts).
const { groups } = JSON.parse(await readFile(resolve(source, 'pages.json'), 'utf8'));
const version = (await readFile(resolve(root, 'server/atelierx/__init__.py'), 'utf8')).match(/__version__ = '([^']+)'/)[1];
const esc = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const files = ['index.md', ...groups.flatMap(g => g.pages.map(p => (g.folder ? `${g.folder}/${p}.md` : `${p}.md`)))];
const pages = await Promise.all(files.map(async file => {
  const text = await readFile(resolve(source, file), 'utf8');
  const head = text.match(/^---\n([\s\S]*?)\n---\n/);
  const md = head ? text.slice(head[0].length) : text;
  return { file, md, head: head?.[1] ?? '', title: md.match(/^# (.+)$/m)?.[1] ?? 'AtelierX', url: file.replace(/\.md$/, '.html') };
}));

// The home page keeps its hero and feature cards in VitePress front matter; read the few keys it uses.
function homeHtml(head, prefix) {
  if (!/^layout: home/m.test(head)) return '';
  const value = key => head.match(new RegExp(`^\\s*${key}: (.+)$`, 'm'))?.[1]?.replace(/^"|"$/g, '') ?? '';
  const pairs = (section, a, b) => {
    const block = head.split(new RegExp(`^${section}:$`, 'm'))[1]?.split(/^\S/m)[0] ?? '';
    return [...block.matchAll(new RegExp(`${a}: (.+)\\n\\s+${b}: (.+)`, 'g'))].map(m => [m[1].replace(/^"|"$/g, ''), m[2].replace(/^"|"$/g, '')]);
  };
  const href = link => (/^https?:/.test(link) ? link : prefix + link.replace(/^\//, '') + '.html');
  const actions = pairs('  actions', 'text', 'link').map(([text, link]) => `<a class="button" href="${esc(href(link))}">${esc(text)}</a>`).join(' ');
  const features = pairs('features', 'title', 'details').map(([title, details]) => `<div class="feature"><strong>${esc(title)}</strong><p>${esc(details)}</p></div>`).join('');
  return `<section class="home-hero"><div><h1>${esc(value('name'))}</h1><p class="home-text">${esc(value('text'))}</p><p class="home-tagline">${esc(value('tagline'))}</p><p class="home-actions">${actions}</p></div><img src="${prefix}icon.svg" alt="" width="160" height="160"></section><section class="home-features">${features}</section>`;
}

for (let n = 0; n < pages.length; n++) {
  const page = pages[n];
  const prefix = page.file.includes('/') ? '../' : '';
  const link = p => prefix + p.url;
  let body = homeHtml(page.head, prefix) + marked.parse(page.md).replace(/href="([^"#:]+)\.md(#[^"]*)?"/g, 'href="$1.html$2"');
  const headings = [];
  body = body.replace(/<h([1-6])>(.*?)<\/h\1>/g, (_, level, text) => {
    const id = `section-${headings.length}`;
    headings.push({ id, text: text.replace(/<[^>]+>/g, ''), level });
    return `<h${level} id="${id}">${text}</h${level}>`;
  });
  const nav = [`<a href="${prefix}index.html"${n === 0 ? ' aria-current="page"' : ''}>처음 화면</a>`]
    .concat(groups.map(g => `<strong>${esc(g.text)}</strong>` + pages.filter(p => p.file !== 'index.md' && (g.folder ? p.file.startsWith(`${g.folder}/`) : !p.file.includes('/'))).map(p => `<a href="${link(p)}"${p === page ? ' aria-current="page"' : ''}>${esc(p.title)}</a>`).join('')))
    .join('');
  // The home page opens with its hero; a page index above it would come first.
  const toc = page.head ? '' : headings.filter(h => h.level === '2').map(h => `<a href="#${h.id}">${h.text}</a>`).join(' · ');
  const prev = pages[n - 1], next = pages[n + 1];
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(page.title)} · AtelierX</title><link rel="stylesheet" href="${prefix}manual.css"></head><body>
<a class="skip-link" href="#main">본문으로 건너뛰기</a><header class="topbar"><a class="brand" href="${prefix}index.html"><img src="${prefix}icon.svg" alt="" width="22" height="22">AtelierX <span>사용 설명서</span></a><button class="nav-toggle" aria-controls="sidebar" aria-expanded="false">목차</button><label class="search-wrap">검색 <input type="search" aria-label="설명서 검색"></label></header>
<div class="layout"><aside class="sidebar" id="sidebar"><nav aria-label="전체 목차">${nav}</nav></aside><main id="main"><div id="search-results" aria-live="polite"></div><article class="manual-section"><nav aria-label="이 페이지">${toc}</nav>${body}</article><footer class="page-footer">${prev ? `<a href="${link(prev)}">← ${esc(prev.title)}</a>` : ''} ${next ? `<a href="${link(next)}">${esc(next.title)} →</a>` : ''}<p>AtelierX ${esc(version)} 기준 · 오프라인 설명서</p></footer></main></div>
<script src="${prefix}search-data.js"></script><script src="${prefix}offline.js"></script></body></html>`;
  await mkdir(dirname(resolve(output, page.url)), { recursive: true });
  await writeFile(resolve(output, page.url), html);
}
await writeFile(resolve(output, 'search-data.js'), `window.manualPages=${JSON.stringify(pages.map(p => ({ title: p.title, url: p.url, text: p.md }))).replaceAll('<', '\\u003c')};`);
console.log(`Rendered ${pages.length} pages to ${relative(root, output)}`);
