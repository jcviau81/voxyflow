import { useToastStore } from '../../stores/useToastStore';
import { cn } from '../../lib/utils';

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismissToast = useToastStore((s) => s.dismissToast);

  if (!toasts.length) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          onClick={() => dismissToast(toast.id)}
          className={cn(
            'flex items-center gap-2 px-4 py-2.5 rounded-lg shadow-lg',
            'pointer-events-auto cursor-pointer text-sm font-medium text-white',
            'animate-in slide-in-from-bottom-2 fade-in duration-200',
            toast.type === 'success' && 'bg-green-700',
            toast.type === 'error' && 'bg-red-700',
            toast.type === 'info' && 'bg-zinc-700',
          )}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
