import './styles/main.css';
import './styles/components.css';
import './styles/opportunities.css';
import './styles/ideas.css';
import './styles/freeboard.css';
import './styles/stats.css';
import './styles/roadmap.css';
import './styles/wiki.css';
import './styles/sprint.css';
import './styles/responsive.css';
import './styles/rich-chat.css';
import './styles/notifications.css';
import './styles/projects-overview.css';
import { App } from './App';
// Import ThemeService early so appearance settings are applied before first render
import { themeService as _themeService } from './services/ThemeService';
void _themeService; // ensure module is loaded and settings applied

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
