/**
 * Appearance constants — mirrors ThemeService.ts from the vanilla frontend.
 * Used by useThemeStore and AppearancePanel.
 */

export type FontSize = 'small' | 'medium' | 'large' | 'x-large' | 'xx-large';
export type SidebarWidth = 'compact' | 'normal' | 'wide';
export type CardDensity = 'comfortable' | 'compact';
export type AnimationSpeed = 'off' | 'normal' | 'snappy';

/** Accent color presets — name shown in UI, value is the hex applied to --color-accent */
export const ACCENT_PRESETS: Array<{ name: string; value: string }> = [
  { name: 'Coral',  value: '#ff6b6b' },
  { name: 'Purple', value: '#6c5ce7' },
  { name: 'Blue',   value: '#0984e3' },
  { name: 'Green',  value: '#00b894' },
  { name: 'Red',    value: '#d63031' },
  { name: 'Orange', value: '#e17055' },
  { name: 'Pink',   value: '#fd79a8' },
  { name: 'Teal',   value: '#00cec9' },
  { name: 'Yellow', value: '#fdcb6e' },
];

export const DEFAULT_ACCENT = '#ff6b6b';

export const FONT_SIZE_MAP: Record<FontSize, { base: string; card: string }> = {
  small:      { base: '14px', card: '13px' },
  medium:     { base: '16px', card: '15px' },
  large:      { base: '20px', card: '19px' },
  'x-large':  { base: '24px', card: '23px' },
  'xx-large': { base: '28px', card: '27px' },
};

export const SIDEBAR_WIDTH_MAP: Record<SidebarWidth, string> = {
  compact: '220px',
  normal:  '280px',
  wide:    '360px',
};

export const TRANSITION_MAP: Record<AnimationSpeed, { transition: string; transitionFast: string }> = {
  off:    { transition: '0s',         transitionFast: '0s' },
  normal: { transition: '0.2s ease',  transitionFast: '0.12s ease' },
  snappy: { transition: '0.1s ease',  transitionFast: '0.06s ease' },
};

// ── CSS variable helpers ───────────────────────────────────────────────────

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function darken(hex: string, amount: number): string {
  const r = Math.max(0, parseInt(hex.slice(1, 3), 16) - amount);
  const g = Math.max(0, parseInt(hex.slice(3, 5), 16) - amount);
  const b = Math.max(0, parseInt(hex.slice(5, 7), 16) - amount);
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
}

/** Returns '#0a0a0f' or '#ffffff' depending on which has better contrast with hex. */
function contrastForeground(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const lum = 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
  return lum > 0.179 ? '#0a0a0f' : '#ffffff';
}

export function applyAccentColor(hex: string): void {
  const root = document.documentElement;
  const fg = contrastForeground(hex);

  // Our custom vars (used by legacy CSS)
  root.style.setProperty('--color-accent', hex);
  root.style.setProperty('--color-accent-hover', darken(hex, 10));
  root.style.setProperty('--color-accent-glow', hexToRgba(hex, 0.15));
  root.style.setProperty('--color-border-focus', hexToRgba(hex, 0.5));
  root.style.setProperty('--color-primary', hex);

  // Shadcn/Tailwind tokens — makes bg-primary, border-primary, text-primary follow the accent
  root.style.setProperty('--primary', hex);
  root.style.setProperty('--primary-foreground', fg);
  root.style.setProperty('--ring', hex);
}

export function applyFontSize(size: FontSize): void {
  const { base, card } = FONT_SIZE_MAP[size];
  document.documentElement.style.setProperty('--font-size-base', base);
  document.documentElement.style.setProperty('--card-font-size', card);
  document.documentElement.style.fontSize = base;
}

export function applySidebarWidth(width: SidebarWidth): void {
  document.documentElement.style.setProperty('--sidebar-width', SIDEBAR_WIDTH_MAP[width]);
}

export function applyCardDensity(density: CardDensity): void {
  document.documentElement.classList.toggle('density-compact', density === 'compact');
  const appContainer = document.querySelector('.app-container');
  if (appContainer) {
    appContainer.classList.toggle('density-compact', density === 'compact');
  }
}

export function applyAnimationSpeed(speed: AnimationSpeed): void {
  const { transition, transitionFast } = TRANSITION_MAP[speed];
  document.documentElement.style.setProperty('--transition', transition);
  document.documentElement.style.setProperty('--transition-fast', transitionFast);
}
