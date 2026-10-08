import { defineConfig } from 'vitepress';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Page order lives in pages.json, shared with the offline manual (tools/render_manual.mjs).
const manual = fileURLToPath(new URL('../', import.meta.url));
const { groups } = JSON.parse(readFileSync(`${manual}/pages.json`, 'utf8'));
const titleOf = (path: string) => readFileSync(`${manual}/${path}.md`, 'utf8').match(/^# (.+)$/m)?.[1] ?? path;
const sidebar = groups.map((group: { text: string; folder: string; pages: string[] }) => ({
  text: group.text,
  items: group.pages.map((page) => {
    const path = group.folder ? `${group.folder}/${page}` : page;
    return { text: titleOf(path), link: `/${path}` };
  }),
}));
// The manual describes the app version in the same commit; there is one place for it.
const version = readFileSync(fileURLToPath(new URL('../../../server/atelierx/__init__.py', import.meta.url)), 'utf8').match(/__version__ = '([^']+)'/)![1];
const base = process.env.DOCS_BASE || '/';
if (!base.startsWith('/') || !base.endsWith('/') || base.includes('..')) throw new Error('DOCS_BASE must be an absolute URL path ending in /');

export default defineConfig({
  lang: 'ko-KR', title: 'AtelierX', description: '쓰고, 그리고, 대화로 다듬는 RP 챗봇 작업실',
  base, outDir: '../../dist/manual-site',
  srcExclude: ['node_modules/**', 'README.md'],
  cleanUrls: false,
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}icon.svg` }],
    // Visit counts and referrers for the online site, without cookies. The offline manual in the app is rendered
    // separately (tools/render_manual.mjs) and never loads it.
    ['script', { type: 'module', src: 'https://static.cloudflareinsights.com/beacon.min.js', 'data-cf-beacon': '{"token": "11572766391e4631a4e44849c39ebe56"}' }],
  ],
  themeConfig: {
    logo: '/icon.svg',
    nav: [
      { text: '처음 사용하기', link: '/tutorial/first-run' },
      { text: '사용 설명서', link: '/guide/getting-started' },
      { text: `${version} 기준`, link: '/changelog' },
      { text: '다운로드', link: 'https://github.com/kiritype/AtelierX/releases/latest' },
    ],
    sidebar,
    socialLinks: [{ icon: 'github', link: 'https://github.com/kiritype/AtelierX' }],
    footer: { message: `AtelierX ${version} 기준 설명서 · MIT License · 방문 통계는 쿠키 없이 수집합니다(Cloudflare Web Analytics)`, copyright: '© 2026 kiritype' },
    search: { provider: 'local', options: { locales: { root: { translations: {
      button: { buttonText: '검색', buttonAriaLabel: '설명서 검색' },
      modal: { noResultsText: '검색 결과가 없습니다', resetButtonTitle: '검색 초기화', footer: { selectText: '선택', navigateText: '이동', closeText: '닫기' } },
    } } } } },
    outline: { label: '이 페이지', level: [2, 3] },
    docFooter: { prev: '이전', next: '다음' },
    sidebarMenuLabel: '목차', returnToTopLabel: '맨 위로', darkModeSwitchLabel: '테마',
  },
});
