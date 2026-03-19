/**
 * ThemeService — Manages all appearance settings (accent color, font size,
 * sidebar width, card density, animation speed). Reads from localStorage on
 * init and applies CSS variables to :root immediately.
 */

export type AccentColor = string; // hex value
export type FontSize    = 'small' | 'medium' | 'large' | 'x-large' | 'xx-large';
export type SidebarWidth = 'compact' | 'normal' | 'wide';
export type CardDensity  = 'comfortable' | 'compact';
export type AnimationSpeed = 'off' | 'normal' | 'snappy';

export const ACCENT_PRESETS: Array<{ name: string; value: string }> = [
  { name: 'Purple',  value: '#6c5ce7' },
  { name: 'Blue',    value: '#0984e3' },
  { name: 'Green',   value: '#00b894' },
  { name: 'Red',     value: '#d63031' },
  { name: 'Orange',  value: '#e17055' },
  { name: 'Pink',    value: '#fd79a8' },
  { name: 'Teal',    value: '#00cec9' },
  { name: 'Yellow',  value: '#fdcb6e' },
];

const FONT_SIZE_MAP: Record<FontSize, { base: string; card: string }> = {
  small:    { base: '14px', card: '13px' },
  medium:   { base: '16px', card: '15px' },
  large:    { base: '20px', card: '19px' },
  'x-large': { base: '24px', card: '23px' },
  'xx-large': { base: '28px', card: '27px' },
};


const SIDEBAR_WIDTH_MAP: Record<SidebarWidth, string> = {
  compact: '220px',
  normal:  '280px',
  wide:    '360px',
};

const TRANSITION_MAP: Record<AnimationSpeed, { transition: string; transitionFast: string }> = {
  off:     { transition: '0s',    transitionFast: '0s' },
  normal:  { transition: '0.2s ease', transitionFast: '0.12s ease' },
  snappy:  { transition: '0.1s ease', transitionFast: '0.06s ease' },
};

const LS = {
  ACCENT:    'voxy_accent_color',
  FONT_SIZE: 'voxy_font_size',
  SIDEBAR:   'voxy_sidebar_width',
  DENSITY:   'voxy_card_density',
  ANIM:      'voxy_animation_speed',
} as const;

class ThemeService {
  // ── Internal state ─────────────────────────────────────────────────────────
  private _accent: AccentColor     = '#6c5ce7';
  private _fontSize: FontSize      = 'medium';
  private _sidebarWidth: SidebarWidth = 'normal';
  private _cardDensity: CardDensity   = 'comfortable';
  private _animSpeed: AnimationSpeed  = 'normal';

  constructor() {
    this.loadAll();
  }

  // ── Public getters ─────────────────────────────────────────────────────────
  get accentColor():    AccentColor    { return this._accent; }
  get fontSize():       FontSize       { return this._fontSize; }
  get sidebarWidth():   SidebarWidth   { return this._sidebarWidth; }
  get cardDensity():    CardDensity    { return this._cardDensity; }
  get animationSpeed(): AnimationSpeed { return this._animSpeed; }

  // ── Setters (live update + persist) ────────────────────────────────────────
  setAccentColor(hex: string): void {
    this._accent = hex;
    localStorage.setItem(LS.ACCENT, hex);
    document.documentElement.style.setProperty('--color-accent', hex);
    // Update glow / hover derived vars automatically
    document.documentElement.style.setProperty('--color-accent-hover', this._darken(hex, 10));
    document.documentElement.style.setProperty('--color-accent-glow', this._hexToRgba(hex, 0.15));
    document.documentElement.style.setProperty('--color-border-focus', this._hexToRgba(hex, 0.5));
  }

  setFontSize(size: FontSize): void {
    this._fontSize = size;
    localStorage.setItem(LS.FONT_SIZE, size);
    const { base, card } = FONT_SIZE_MAP[size];
    document.documentElement.style.setProperty('--font-size-base', base);
    document.documentElement.style.setProperty('--card-font-size', card);
    document.documentElement.style.fontSize = base;
  }

  setSidebarWidth(width: SidebarWidth): void {
    this._sidebarWidth = width;
    localStorage.setItem(LS.SIDEBAR, width);
    document.documentElement.style.setProperty('--sidebar-width', SIDEBAR_WIDTH_MAP[width]);
  }

  setCardDensity(density: CardDensity): void {
    this._cardDensity = density;
    localStorage.setItem(LS.DENSITY, density);
    const root = document.querySelector('.app-container') as HTMLElement | null;
    if (root) {
      root.classList.toggle('density-compact', density === 'compact');
    }
    // Also set on documentElement as fallback
    document.documentElement.classList.toggle('density-compact', density === 'compact');
  }

  setAnimationSpeed(speed: AnimationSpeed): void {
    this._animSpeed = speed;
    localStorage.setItem(LS.ANIM, speed);
    const { transition, transitionFast } = TRANSITION_MAP[speed];
    document.documentElement.style.setProperty('--transition', transition);
    document.documentElement.style.setProperty('--transition-fast', transitionFast);
  }

  // ── Load all settings from localStorage ────────────────────────────────────
  loadAll(): void {
    const accent = localStorage.getItem(LS.ACCENT);
    if (accent) this.setAccentColor(accent);

    const fontSize = localStorage.getItem(LS.FONT_SIZE) as FontSize | null;
    this.setFontSize(fontSize && fontSize in FONT_SIZE_MAP ? fontSize : this._fontSize);

    const sidebar = localStorage.getItem(LS.SIDEBAR) as SidebarWidth | null;
    if (sidebar && sidebar in SIDEBAR_WIDTH_MAP) this.setSidebarWidth(sidebar);

    const density = localStorage.getItem(LS.DENSITY) as CardDensity | null;
    if (density && (density === 'comfortable' || density === 'compact')) this.setCardDensity(density);

    const anim = localStorage.getItem(LS.ANIM) as AnimationSpeed | null;
    if (anim && anim in TRANSITION_MAP) this.setAnimationSpeed(anim);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  private _hexToRgba(hex: string, alpha: number): string {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  private _darken(hex: string, amount: number): string {
    const r = Math.max(0, parseInt(hex.slice(1, 3), 16) - amount);
    const g = Math.max(0, parseInt(hex.slice(3, 5), 16) - amount);
    const b = Math.max(0, parseInt(hex.slice(5, 7), 16) - amount);
    return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`;
  }
}

export const themeService = new ThemeService();
