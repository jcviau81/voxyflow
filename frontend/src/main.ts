import './styles/main.css';
import './styles/components.css';
import './styles/opportunities.css';
import './styles/ideas.css';
import './styles/responsive.css';
import './styles/rich-chat.css';
import { App } from './App';

// Initialize app when DOM is ready
const init = (): void => {
  const root = document.getElementById('app');
  if (!root) {
    console.error('[Voxyflow] Root element #app not found');
    return;
  }

  const app = new App(root);

  // Hot Module Replacement
  if ((module as unknown as { hot?: { dispose: (cb: () => void) => void } }).hot) {
    (module as unknown as { hot: { dispose: (cb: () => void) => void } }).hot.dispose(() => {
      app.destroy();
    });
  }

  // Register service worker
  if ('serviceWorker' in navigator && process.env.NODE_ENV === 'production') {
    navigator.serviceWorker
      .register('/sw.js')
      .then((reg) => {
        console.log('[Voxyflow] Service Worker registered:', reg.scope);
      })
      .catch((err) => {
        console.error('[Voxyflow] Service Worker registration failed:', err);
      });
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
