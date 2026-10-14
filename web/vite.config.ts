import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';

const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'));

// In development the Python server runs on 8765 and Vite proxies /api to it.
export default defineConfig({
  plugins: [react(), {
    name: 'preview-sandbox',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split('?')[0] === '/preview.html') {
          res.setHeader('Content-Security-Policy', "sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src ws://localhost:5173 ws://127.0.0.1:5173; base-uri 'none'; form-action 'none'; frame-ancestors 'self'");
        }
        next();
      });
    },
  }],
  define: { __APP_VERSION__: JSON.stringify(version) },
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
    rolldownOptions: {
      input: { main: 'index.html', preview: 'preview.html' },
      // The editor's language parsers apart from the editor itself, so no chunk passes the size warning (#83).
      output: {
        codeSplitting: {
          groups: [{ name: 'editor-languages', test: /[\\/]node_modules[\\/](@codemirror[\\/]lang-|@lezer[\\/](javascript|markdown|html|css))/ }],
        },
      },
    },
  },
});
