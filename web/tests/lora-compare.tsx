// Browser fixture for training → comparison handoff. No real API requests or generation.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRoot } from 'react-dom/client';
import { useState } from 'react';
import ImageLora from '../src/components/image/ImageLora';
import ImageLab from '../src/components/image/ImageLab';
import { ToastProvider, Toasts } from '../src/components/Toasts';
import '../src/styles.css';

const reply = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
const epochs = [2, 4];
const dataset = { id: 'D001', name: 'Fixture', outfits: ['o01'], triggers: { character: 'test_character', outfit: 'test_outfit' }, items: [{ image: { path: 'test.png' }, caption: 'test_character, test_outfit, 1girl', outfit_id: 'o01' }] };
window.fetch = async (input, options) => {
  const url = String(input);
  if (url.endsWith('/image/designs')) return reply([{ id: 'C001', name: 'Test', has_design: true, outfits: [] }]);
  if (url.includes('/candidates')) return reply([]);
  if (url.endsWith('/training/status')) return reply({ bases: [], trainer_found: false });
  if (url.endsWith('/catalog')) return reply({ connected: true, models: ['anima-base.safetensors'], text_encoders: [], vaes: [], loras: epochs.map((e) => `anima\\test-e${e}.safetensors`), samplers: ['er_sde'], schedulers: ['simple'], defaults: {} });
  if (url.endsWith('/presets')) return reply([]);
  if (url.endsWith('/lab/runs')) return reply({ runs: [] });
  if (url.endsWith('/lab')) {
    document.getElementById('request')!.textContent = String(options?.body);
    return reply({ count: 2, lab_group: 'fixture' });
  }
  return reply({ datasets: [dataset], models: [], busy: false, runs: [{ id: 'R001', status: 'done', dataset: 'D001', base_model: 'anima-base', settings: { method: 'tlora', epochs: 4 }, outputs: epochs.map((epoch) => ({ epoch, file: { path: `test-e${epoch}.safetensors`, size: 1 } })), progress: {} }] });
};
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function Fixture() {
  const [lab, setLab] = useState(false);
  return <QueryClientProvider client={client}><ToastProvider>
    <h2>Synthetic training → comparison test</h2>
    {lab ? <ImageLab /> : <ImageLora workId="TEST" openLab={() => setLab(true)} />}
    <pre id="request" /><Toasts />
  </ToastProvider></QueryClientProvider>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
