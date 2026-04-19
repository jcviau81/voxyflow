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
          // Exclude large WASM/ML model files from precache
          globIgnores: ['**/*.wasm', '**/whisper.worker*.js'],
          maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
          // Wipe stale precache entries on activation — prevents zombie bundles
          // when the SW updates (e.g. after a cross-device sync fix deploy).
          cleanupOutdatedCaches: true,
          // Always fetch fresh JS/CSS — network first, fall back to cache.
          // Bump cacheName when we need to force clients past a bad cached
          // bundle (increment the -vN suffix on each forced invalidation).
          runtimeCaching: [
            {
              urlPattern: /\.(?:js|css)$/,
              handler: 'NetworkFirst',
              options: { cacheName: 'assets-v2', networkTimeoutSeconds: 5 },
            },
          ],
          skipWaiting: true,
          clientsClaim: true,
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
