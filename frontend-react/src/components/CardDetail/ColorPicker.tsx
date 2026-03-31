import { cn } from '@/lib/utils';

type CardColor = 'yellow' | 'blue' | 'green' | 'pink' | 'purple' | 'orange';

const COLOR_OPTIONS: { value: CardColor | null; label: string; swatch: string }[] = [
  { value: null, label: 'None', swatch: 'bg-muted border-dashed' },
  { value: 'yellow', label: 'Yellow', swatch: 'bg-yellow-400/60' },
  { value: 'blue', label: 'Blue', swatch: 'bg-blue-400/60' },
  { value: 'green', label: 'Green', swatch: 'bg-emerald-400/60' },
  { value: 'pink', label: 'Pink', swatch: 'bg-pink-400/60' },
  { value: 'purple', label: 'Purple', swatch: 'bg-purple-400/60' },
  { value: 'orange', label: 'Orange', swatch: 'bg-orange-400/60' },
];

interface ColorPickerProps {
  current: CardColor | null | undefined;
  onChange: (color: CardColor | null) => void;
}

export function ColorPicker({ current, onChange }: ColorPickerProps) {
  const selected = current ?? null;

  return (
    <div className="flex gap-2">
      {COLOR_OPTIONS.map(({ value, label, swatch }) => (
        <button
          key={label}
          type="button"
          title={label}
          onClick={() => onChange(value)}
          className={cn(
            'h-6 w-6 rounded-full border-2 transition-transform hover:scale-110',
            swatch,
            selected === value
              ? 'border-foreground ring-2 ring-foreground/20'
              : 'border-transparent',
          )}
        />
      ))}
    </div>
  );
}
