# Voxyflow Deployment Guide

## Development

### Prerequisites

- Node.js 18+
- npm 9+

### Setup

```bash
cd voxyflow/frontend
npm install
cp .env.example .env
# Edit .env if needed
npm run dev
```

Dev server runs at `http://localhost:3000` with HMR and backend proxy.

## Production Build

```bash
npm run build
```

Output: `dist/` directory containing:
- `index.html` — entry point
- `js/main.[hash].js` — application bundle
- `js/vendor.[hash].js` — vendor chunk
- `css/main.[hash].css` — extracted styles
- `manifest.json` — PWA manifest
- `sw.js` — service worker (Workbox-generated)
- `icons/` — app icons

## Deployment Options

### 1. Static Hosting (Recommended)

The `dist/` folder is a static site. Deploy to:

**Nginx:**

```nginx
server {
    listen 80;
    server_name voxyflow.example.com;
    root /var/www/voxyflow/dist;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # WebSocket proxy
    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # API proxy
    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
```

**Caddy:**

```caddyfile
voxyflow.example.com {
    root * /var/www/voxyflow/dist
    file_server
    try_files {path} /index.html

    reverse_proxy /ws localhost:8000
    reverse_proxy /api/* localhost:8000

    header {
        X-Frame-Options "SAMEORIGIN"
        X-Content-Type-Options "nosniff"
    }
}
```

### 2. GitHub Pages / Vercel / Netlify

```bash
# Vercel
npx vercel --prod

# Netlify
npx netlify deploy --prod --dir=dist
```

Note: Configure redirects for SPA routing:
- Netlify: `_redirects` file with `/* /index.html 200`
- Vercel: `vercel.json` with rewrites

## PWA Installation

### Desktop (Chrome/Edge)

1. Visit the app URL
2. Click install icon in address bar
3. Or: Menu → "Install Voxyflow"

### Mobile (iOS)

1. Open in Safari
2. Tap Share → "Add to Home Screen"

### Mobile (Android)

1. Open in Chrome
2. Tap "Add to Home Screen" banner
3. Or: Menu → "Install app"

## Backend systemd Service

Voxyflow is a single-user install — the backend runs as a **user-level** systemd
service (not system-wide). Enable linger so the service starts at boot without login:

```bash
sudo loginctl enable-linger "$USER"
```

```ini
# ~/.config/systemd/user/voxyflow-backend.service
[Unit]
Description=Voxyflow Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/youruser/voxyflow/backend
EnvironmentFile=/home/youruser/voxyflow/backend/.env
ExecStart=/home/youruser/voxyflow/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

> **Important:** The `EnvironmentFile=` line must point to your `backend/.env` file.
> Without it, the service won't load `DATABASE_URL` and the app will use the default path,
> which could create a second database if the default doesn't match your `.env`.

```bash
systemctl --user daemon-reload
systemctl --user enable --now voxyflow-backend
journalctl --user -u voxyflow-backend -f  # watch logs
```

## Environment Variables

### Frontend

| Variable | Default | Description |
|----------|---------|-------------|
| `VOXYFLOW_WS_URL` | `ws://localhost:8000` | WebSocket backend URL |
| `VOXYFLOW_API_URL` | `http://localhost:8000` | REST API URL |
| `NODE_ENV` | `development` | Environment |

For production, set these at build time or configure the reverse proxy.

### Backend

See `backend/.env.example` for the full list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `~/.voxyflow/voxyflow.db` | SQLite database path |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `CLAUDE_USE_CLI` | `false` | Map to the `claude_use_cli` setting — `true` spawns the `claude -p` CLI subprocess. Prefer the Settings UI. |
| `CLAUDE_API_KEY` | (keyring) | API key for native SDK path (prefer the Settings UI, or `keyring set voxyflow claude_api_key`) |
| `DEBUG` | `false` | Enable debug logging |

See [`docs/CONFIG.md`](CONFIG.md) for the live runtime toggles
(`VOXYFLOW_CLOSEOUT_PASS`, `DISPATCHER_WORKER_CALLBACK`, `VOXYFLOW_DEV_TASK`)
and retired ones (`CLAUDE_PROXY_URL`, `voxyflow-proxy`).

## SSL/TLS

For production, always use HTTPS:
- WebSocket URL becomes `wss://`
- Required for service worker
- Required for Web Speech API
- Required for microphone access

## Monitoring

The frontend logs to browser console:
- `[ApiClient]` — WebSocket connection events
- `[SttService]` — Voice input events
- `[AudioService]` — Audio playback events
- `[StorageService]` — IndexedDB operations
- `[AppState]` — State persistence issues
- `[Voxyflow]` — App-level events

## Troubleshooting

### WebSocket Won't Connect

1. Check backend is running on port 8000
2. Verify `VOXYFLOW_WS_URL` is correct
3. Check browser console for errors
4. Ensure no firewall blocking WebSocket

### Microphone Not Working

1. Check browser permissions (Settings → Privacy → Microphone)
2. HTTPS is required for microphone access
3. Only one tab can use the microphone at a time

### PWA Not Installing

1. Must be served over HTTPS
2. `manifest.json` must be valid
3. Service worker must be registered
4. Check Chrome DevTools → Application → Manifest

### Offline Mode

1. Visit the app at least once while online
2. Service worker caches assets
3. Messages are queued in IndexedDB
4. Queued messages sent when reconnected
