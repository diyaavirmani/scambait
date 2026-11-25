import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The build goes into app/web/dist, served by FastAPI on the same origin as the API, so no URLs are hard-coded.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../app/web/dist', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  esbuild: { charset: 'ascii' },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000', '/lab': 'http://127.0.0.1:8000' },
  },
});
