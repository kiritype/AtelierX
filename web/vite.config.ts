import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In development the Python server runs on 8765 and Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // The JSX preview frame is sandboxed (opaque origin, sends `Origin: null`); it must still load its own modules.
    cors: { origin: [/^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?$/, 'null'] },
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rolldownOptions: { input: { main: 'index.html', preview: 'preview.html' } },
  },
});
