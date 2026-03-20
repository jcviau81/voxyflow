import './styles/main.css';
import './styles/components.css';
import './styles/opportunities.css';
import './styles/ideas.css';
import './styles/freeboard.css';
import './styles/stats.css';
import './styles/roadmap.css';
import './styles/wiki.css';
import './styles/sprint.css';
import './styles/docs.css';
import './styles/knowledge.css';
import './styles/meeting-notes.css';
import './styles/responsive.css';
import './styles/rich-chat.css';
import './styles/notifications.css';
import './styles/projects-overview.css';
import './styles/task-panel.css';
import './styles/worker-panel.css';
import { App } from './App';
import { OnboardingPage } from './components/Onboarding/OnboardingPage';
import { API_URL } from './utils/constants';
// Import ThemeService early so appearance settings are applied before first render
import { themeService as _themeService } from './services/ThemeService';
void _themeService; // ensure module is loaded and settings applied

async function needsOnboarding(): Promise<boolean> {
  try {
    const response = await fetch(`${API_URL}/api/settings`);
    if (!response.ok) return true; // Backend down or no settings → show onboarding
    const data = await response.json();
    return !data.onboarding_complete;
  } catch {
    return true; // Can't reach backend → show onboarding
  }
}

// Initialize app when DOM is ready
const init = async (): Promise<void> => {
  const root = document.getElementById('app');
  if (!root) {
    console.error('[Voxyflow] Root element #app not found');
    return;
  }

  // Check if onboarding is needed
  const showOnboarding = await needsOnboarding();

  if (showOnboarding) {
    const onboarding = new OnboardingPage(root);

    // HMR support for onboarding
    if ((module as unknown as { hot?: { dispose: (cb: () => void) => void } }).hot) {
      (module as unknown as { hot: { dispose: (cb: () => void) => void } }).hot.dispose(() => {
        onboarding.destroy();
      });
    }
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
