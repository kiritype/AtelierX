// Manual browser regression fixture: start Vite and open /tests/lora-review.html.
// Uses synthetic in-memory data only; no requests reach the app or image server.
// Check: failed caption saves retain edits; successful saves persist; edits typed
// during a delayed save survive; switching cached characters resets their forms.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRoot } from 'react-dom/client';
import { useState } from 'react';
import ImageLora from '../src/components/image/ImageLora';
import { ToastProvider, Toasts } from '../src/components/Toasts';
import { setLanguage } from '../src/i18n';
import '../src/styles.css';

setLanguage('ko');
const characters = ['C001', 'C002'];
const records = Object.fromEntries(characters.map((id) => [id, {
  datasets: [{
    id: 'D001', name: `${id} dataset`, outfits: ['o01'],
    triggers: { character: id.toLowerCase(), outfit: `${id.toLowerCase()}_o01` },
    items: [{ image: { path: `${id}.png`, sha256: 'test-only' }, outfit_id: 'o01', expression_id: 'neutral', caption: `${id} original caption`, edited: false }],
  }], runs: [], models: [], busy: false,
}]));
let failure = true;
let delayed = false;
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
window.fetch = async (input, options) => {
  const url = String(input);
  if (url.includes('/thumbnail')) return new Response('', { status: 404 });
  if (url.endsWith('/image/designs')) return response(characters.map((id) => ({ id, name: `Test ${id}`, has_design: true, trigger: id.toLowerCase(), outfits: [{ id: 'o01', name: `${id} outfit` }] })));
  const id = characters.find((candidate) => url.includes(`/lora/${candidate}`));
  if (!id) return response({ error: { key: 'fixture', text: `Unexpected fixture request: ${url}` } }, 500);
  if (url.includes('/candidates')) return response([]);
  if (options?.method === 'POST' && url.endsWith('/captions')) {
    const body = JSON.parse(String(options.body));
    if (delayed) await new Promise((resolve) => setTimeout(resolve, 2500));
    if (failure) return response({ error: { key: 'fixture.save_failed', text: 'Fixture: caption save failed. Your edit must remain.' } }, 503);
    for (const item of records[id].datasets[0].items) {
      if (body.items?.[item.image.path] !== undefined) {
        item.caption = body.items[item.image.path];
        item.edited = true;
      }
    }
    return response(records[id].datasets[0]);
  }
  return response(records[id]);
};
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function Fixture() {
  const [fail, setFail] = useState(failure);
  const [delay, setDelay] = useState(delayed);
  return <QueryClientProvider client={client}><ToastProvider>
    <div className="pad col">
      <h2>LoRA UI regression fixture — synthetic data</h2>
      <label><input type="checkbox" checked={fail} onChange={(e) => { failure = e.target.checked; setFail(failure); }} />Fail caption saves</label>
      <label><input type="checkbox" checked={delay} onChange={(e) => { delayed = e.target.checked; setDelay(delayed); }} />Delay caption saves</label>
    </div>
    <ImageLora workId="TEST" /><Toasts />
  </ToastProvider></QueryClientProvider>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
