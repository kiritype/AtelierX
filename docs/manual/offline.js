const input = document.querySelector('input[type="search"]');
const results = document.getElementById('search-results');
const base = new URL('.', document.querySelector('script[src$="offline.js"]').src);
input.addEventListener('input', () => {
  results.replaceChildren();
  const query = input.value.trim().toLocaleLowerCase();
  if (!query) return;
  const matches = window.manualPages.filter(p => p.text.toLocaleLowerCase().includes(query));
  const summary = document.createElement('p');
  summary.textContent = `${matches.length}개 문서`;
  results.append(summary);
  for (const page of matches) {
    const link = document.createElement('a');
    link.href = new URL(page.url, base).href;
    link.textContent = page.title;
    const row = document.createElement('p');
    row.append(link);
    results.append(row);
  }
});
document.querySelector('.nav-toggle').addEventListener('click', event => {
  const open = document.getElementById('sidebar').classList.toggle('is-open');
  event.currentTarget.setAttribute('aria-expanded', String(open));
});
