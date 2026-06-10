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
        strategies: 'injectManifest',
        srcDir: 'src',
        filename: 'sw.ts',
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
        injectManifest: {
          // Exclude large WASM/ML model files from precache
          globIgnores: ['**/*.wasm', '**/whisper.worker*.js'],
          maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        }
      })
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          // Rolldown-native chunk grouping (vite 8 = rolldown-vite).
          // NOTE: this replaces the old function-form `manualChunks`. The shim
          // rolldown uses for `manualChunks` mis-placed the react/jsx-runtime
          // CJS interop wrapper inside the `editor` chunk, which force-preloaded
          // ~650 kB of CodeMirror on every page. Explicit groups with priorities
          // fix the placement. `editor` and `voice` are only reachable through
          // dynamic imports (lazy DescriptionEditor / wake-word start).
          codeSplitting: {
            groups: [
              { name: 'react', test: /node_modules\/(?:react|react-dom|react-router|react-router-dom|scheduler)\/|jsx-runtime/, priority: 100 },
              { name: 'query', test: /node_modules\/@tanstack\/react-query\//, priority: 90 },
              { name: 'editor', test: /node_modules\/(?:@uiw\/react-codemirror|@codemirror|@lezer)\//, priority: 90 },
              { name: 'markdown', test: /node_modules\/(?:react-markdown|remark-|rehype-|micromark|mdast-|unist-|hast-|vfile|unified|react-syntax-highlighter)/, priority: 95 },
              { name: 'dnd', test: /node_modules\/@dnd-kit\//, priority: 90 },
              { name: 'voice', test: /node_modules\/(?:@huggingface\/transformers|onnxruntime-web)\//, priority: 90 },
              { name: 'vendor', test: /node_modules/, priority: 10 },
            ],
          },
        },
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
