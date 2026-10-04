import { defineConfig } from 'vitepress';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const guide = fileURLToPath(new URL('../guide/', import.meta.url));
const order = ['getting-started', 'walkthrough', 'editing', 'ai-tools', 'chat-test', 'connections', 'image-setup', 'character-images', 'generation', 'gallery-export', 'lora', 'platforms', 'maintenance', 'release-status'];
const files = readdirSync(guide).filter(f => f.endsWith('.md')).sort((a, b) => order.indexOf(a.slice(0, -3)) - order.indexOf(b.slice(0, -3)));
const items = files.map(file => ({
  text: readFileSync(`${guide}/${file}`, 'utf8').match(/^# (.+)$/m)?.[1] ?? file,
  link: `/guide/${file.slice(0, -3)}`,
}));
const base = process.env.DOCS_BASE || '/';
if (!base.startsWith('/') || !base.endsWith('/') || base.includes('..')) throw new Error('DOCS_BASE must be an absolute URL path ending in /');

export default defineConfig({
  lang: 'ko-KR', title: 'AtelierX', description: '설치부터 작품 작성, 이미지 생성과 배포까지',
  base, outDir: '../../dist/manual-site',
  srcExclude: ['node_modules/**', 'README.md'],
  cleanUrls: false,
  themeConfig: {
    nav: [{ text: '사용 설명서', link: '/' }, { text: '시작하기', link: '/guide/getting-started' }],
    sidebar: [{ text: '사용 설명서', items }],
    search: { provider: 'local', options: { locales: { root: { translations: {
      button: { buttonText: '검색', buttonAriaLabel: '설명서 검색' },
      modal: { noResultsText: '검색 결과가 없습니다', resetButtonTitle: '검색 초기화', footer: { selectText: '선택', navigateText: '이동', closeText: '닫기' } },
    } } } } },
    outline: { label: '이 페이지', level: [2, 3] },
    docFooter: { prev: '이전', next: '다음' },
    sidebarMenuLabel: '목차', returnToTopLabel: '맨 위로', darkModeSwitchLabel: '테마',
  },
});
