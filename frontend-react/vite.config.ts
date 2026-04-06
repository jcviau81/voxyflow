import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';
import fs from 'fs';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [
      react(),
      tailwindcss(),
      VitePWA({
        registerType: 'autoUpdate',
        includeAssets: ['favicon.svg', 'icons.svg'],
        manifest: {
          name: 'Voxyflow',
          short_name: 'Voxyflow',
          description: 'Voice First Automated Development Workflow',
          theme_color: '#000000',
          background_color: '#000000',
          display: 'standalone',
          start_url: '/',
          icons: [
            { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
            { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
            { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' }
          ]
        },
        workbox: {
          // Exclude large WASM/ML model files from precache (they are too large and not suitable for SW caching)
          globIgnores: ['**/*.wasm', '**/whisper.worker*.js'],
          maximumFileSizeToCacheInBytes: 4 * 1024 * 1024, // 4 MiB to cover the main JS bundle
        }
      })
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 3000,
      host: '0.0.0.0',
      https: env.SSL_KEY_PATH ? {
        key: fs.readFileSync(env.SSL_KEY_PATH),
        cert: fs.readFileSync(env.SSL_CERT_PATH),
      } : undefined,
      proxy: {
        '/api': 'http://localhost:8000',
        '/ws': { target: 'ws://localhost:8000', ws: true },
      },
    },
  };
});
