import './styles/main.css';
import './styles/components.css';
import './styles/opportunities.css';
import './styles/freeboard.css';
import './styles/stats.css';
import './styles/wiki.css';
import './styles/docs.css';
import './styles/knowledge.css';
import './styles/responsive.css';
import './styles/rich-chat.css';
import './styles/notifications.css';
import './styles/projects-overview.css';
import './styles/worker-panel.css';
import { App } from './App';
import { OnboardingPage } from './components/Onboarding/OnboardingPage';
import { API_URL } from './utils/constants';
// Import ThemeService early so appearance settings are applied before first render
import { themeService as _themeService } from './services/ThemeService';
void _themeService; // ensure module is loaded and settings applied

async function needsOnboarding(): Promise<boolean> {
  // Retry up to 3 times with increasing delay — backend may still be starting
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(`${API_URL}/api/settings`);
      if (!response.ok) {
        // Backend responded but with error — wait and retry
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      const data = await response.json();
      // Sync settings to localStorage so TtsService/SttService always have fresh values
      try { localStorage.setItem('voxyflow_settings', JSON.stringify(data)); } catch { /* ignore */ }
      return !data.onboarding_complete;
    } catch {
      // Backend not ready — wait and retry
      await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
    }
  }
  // After 3 retries, also check if projects exist (fallback — already-onboarded user)
  try {
    const res = await fetch(`${API_URL}/api/projects`);
    if (res.ok) {
      const projects = await res.json();
      if (Array.isArray(projects) && projects.length > 0) return false; // Has projects → skip onboarding
    }
  } catch { /* ignore */ }
  return true;
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
