/**
 * PageHeader — top bar for full-page views (Settings, Jobs, Projects).
 *
 * Shows a hamburger menu (mobile), page title, and close button that
 * navigates back to the last project/main view.
 */

import { useNavigate } from 'react-router-dom';
import { X, Menu } from 'lucide-react';

interface PageHeaderProps {
  title: string;
  onSidebarToggle?: () => void;
}

export function PageHeader({ title, onSidebarToggle }: PageHeaderProps) {
  const navigate = useNavigate();

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border shrink-0">
      {onSidebarToggle && (
        <button
          className="md:hidden flex items-center justify-center w-8 h-8 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
          onClick={onSidebarToggle}
          title="Menu"
        >
          <Menu size={18} />
        </button>
      )}
      <span className="text-sm font-semibold text-foreground flex-1">{title}</span>
      <button
        className="flex items-center justify-center w-8 h-8 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
        onClick={() => navigate(-1)}
        title="Close"
      >
        <X size={18} />
      </button>
    </div>
  );
}
