/**
 * AppearancePanel — Appearance & theme settings.
 *
 * Mirrors the renderAppearanceSection() + bindAppearanceEvents() from
 * frontend/src/components/Settings/SettingsPage.ts (lines 286–459).
 *
 * Uses React Hook Form to track form state; each change is applied live
 * (no save button needed) via store actions.
 */

import { useEffect } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import { cn } from '../../lib/utils';
import {
  ACCENT_PRESETS,
  type FontSize,
  type SidebarWidth,
  type CardDensity,
  type AnimationSpeed,
} from '../../lib/themeConstants';
import { useThemeStore, type Theme } from '../../stores/useThemeStore';

// ── Types ──────────────────────────────────────────────────────────────────

interface AppearanceFormValues {
  theme: Theme;
  accentColor: string;
  fontSize: FontSize;
  sidebarWidth: SidebarWidth;
  cardDensity: CardDensity;
  animationSpeed: AnimationSpeed;
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface PillGroupProps<T extends string> {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
}

function PillGroup<T extends string>({ options, value, onChange }: PillGroupProps<T>) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            'appearance-pill px-3 py-1 text-xs rounded-md border transition-colors',
            'border-border hover:border-primary hover:text-foreground',
            value === opt.value
              ? 'bg-primary text-primary-foreground border-primary font-medium'
              : 'bg-transparent text-muted-foreground',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

interface SettingRowProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

function SettingRow({ label, description, children }: SettingRowProps) {
  return (
    <div className="setting-row flex items-start justify-between gap-4 py-4 border-b border-border last:border-0">
      <div className="setting-info min-w-0 shrink-0 w-52">
        <div className="setting-label text-sm font-medium text-foreground">{label}</div>
        {description && (
          <div className="setting-description text-xs text-muted-foreground mt-0.5">{description}</div>
        )}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export function AppearancePanel() {
  const {
    theme,
    accentColor,
    fontSize,
    sidebarWidth,
    cardDensity,
    animationSpeed,
    setTheme,
    setAccentColor,
    setFontSize,
    setSidebarWidth,
    setCardDensity,
    setAnimationSpeed,
  } = useThemeStore();

  const { control } = useForm<AppearanceFormValues>({
    defaultValues: { theme, accentColor, fontSize, sidebarWidth, cardDensity, animationSpeed },
  });

  // Watch all fields and apply live updates via store actions.
  const watched = useWatch({ control });

  useEffect(() => {
    if (watched.theme !== undefined && watched.theme !== theme) setTheme(watched.theme);
  }, [watched.theme]);

  useEffect(() => {
    if (watched.accentColor !== undefined && watched.accentColor !== accentColor)
      setAccentColor(watched.accentColor);
  }, [watched.accentColor]);

  useEffect(() => {
    if (watched.fontSize !== undefined && watched.fontSize !== fontSize) setFontSize(watched.fontSize);
  }, [watched.fontSize]);

  useEffect(() => {
    if (watched.sidebarWidth !== undefined && watched.sidebarWidth !== sidebarWidth)
      setSidebarWidth(watched.sidebarWidth);
  }, [watched.sidebarWidth]);

  useEffect(() => {
    if (watched.cardDensity !== undefined && watched.cardDensity !== cardDensity)
      setCardDensity(watched.cardDensity);
  }, [watched.cardDensity]);

  useEffect(() => {
    if (watched.animationSpeed !== undefined && watched.animationSpeed !== animationSpeed)
      setAnimationSpeed(watched.animationSpeed);
  }, [watched.animationSpeed]);

  return (
    <div className="appearance-panel p-6 max-w-2xl" data-testid="settings-appearance">
      <h3 className="text-base font-semibold text-foreground mb-1">🎨 Appearance</h3>
      <p className="text-xs text-muted-foreground mb-6">Changes apply immediately and are saved automatically.</p>

      <div className="appearance-grid">

        {/* ── Theme ── */}
        <SettingRow label="Theme" description="Dark or Light interface">
          <Controller
            control={control}
            name="theme"
            render={({ field }) => (
              <PillGroup<Theme>
                options={[
                  { value: 'dark',  label: '🌙 Dark' },
                  { value: 'light', label: '☀️ Light' },
                ]}
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        </SettingRow>

        {/* ── Accent Color ── */}
        <SettingRow label="Accent Color" description="UI highlight color — changes live">
          <Controller
            control={control}
            name="accentColor"
            render={({ field }) => (
              <div className="accent-swatches flex flex-wrap gap-2">
                {ACCENT_PRESETS.map(({ name, value }) => (
                  <button
                    key={value}
                    type="button"
                    title={name}
                    aria-label={`Accent color: ${name}`}
                    onClick={() => field.onChange(value)}
                    style={{ backgroundColor: value }}
                    className={cn(
                      'accent-swatch w-6 h-6 rounded-full border-2 transition-transform',
                      field.value.toLowerCase() === value
                        ? 'border-white scale-110 ring-2 ring-white/40'
                        : 'border-transparent hover:scale-110',
                    )}
                  />
                ))}
              </div>
            )}
          />
        </SettingRow>

        {/* ── Font Size ── */}
        <SettingRow label="Font Size" description="Small (14px) · Medium (16px) · Large (20px)">
          <Controller
            control={control}
            name="fontSize"
            render={({ field }) => (
              <PillGroup<FontSize>
                options={[
                  { value: 'small',    label: 'Small' },
                  { value: 'medium',   label: 'Medium' },
                  { value: 'large',    label: 'Large' },
                  { value: 'x-large',  label: 'X-Large' },
                  { value: 'xx-large', label: 'XX-Large' },
                ]}
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        </SettingRow>

        {/* ── Sidebar Width ── */}
        <SettingRow label="Sidebar Width" description="Compact (220px) · Normal (280px) · Wide (360px)">
          <Controller
            control={control}
            name="sidebarWidth"
            render={({ field }) => (
              <PillGroup<SidebarWidth>
                options={[
                  { value: 'compact', label: 'Compact' },
                  { value: 'normal',  label: 'Normal' },
                  { value: 'wide',    label: 'Wide' },
                ]}
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        </SettingRow>

        {/* ── Card Density ── */}
        <SettingRow label="Card Density" description="Comfortable keeps full padding; Compact is tighter">
          <Controller
            control={control}
            name="cardDensity"
            render={({ field }) => (
              <PillGroup<CardDensity>
                options={[
                  { value: 'comfortable', label: 'Comfortable' },
                  { value: 'compact',     label: 'Compact' },
                ]}
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        </SettingRow>

        {/* ── Animation Speed ── */}
        <SettingRow label="Animation Speed" description="Off disables all transitions">
          <Controller
            control={control}
            name="animationSpeed"
            render={({ field }) => (
              <PillGroup<AnimationSpeed>
                options={[
                  { value: 'off',    label: 'Off' },
                  { value: 'normal', label: 'Normal' },
                  { value: 'snappy', label: 'Snappy' },
                ]}
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        </SettingRow>

      </div>
    </div>
  );
}
