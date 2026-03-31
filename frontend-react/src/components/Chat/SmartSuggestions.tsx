import { useCallback, useMemo, useState } from 'react';
import { useProjectStore } from '../../stores/useProjectStore';
import { cn } from '../../lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ChatLevel = 'general' | 'project' | 'card';

export interface SmartSuggestionsProps {
  chatLevel: ChatLevel;
  projectId?: string;
  onSelect: (text: string) => void;
}

// ---------------------------------------------------------------------------
// Static suggestion sets (no AI calls — all rule-based)
// ---------------------------------------------------------------------------

function getContextSuggestions(level: ChatLevel, projectName?: string): string[] {
  switch (level) {
    case 'general':
      return [
        'Create a new project',
        'What can you help me with?',
        'Show my projects',
      ];
    case 'project':
      return [
        'Create a card',
        'Show the kanban board',
        "What's the project status?",
        `Help me with ${projectName || 'this project'}`,
      ];
    case 'card':
      return [
        'Help me implement this',
        'Write tests for this',
        'What are the next steps?',
        'Break this into smaller tasks',
      ];
    default:
      return [];
  }
}

function getFollowUpSuggestions(responseContent: string): string[] {
  const lower = responseContent.toLowerCase();

  const mentionsCode =
    lower.includes('```') ||
    lower.includes('function') ||
    lower.includes('implementation') ||
    lower.includes('code') ||
    lower.includes('snippet');

  const mentionsTasks =
    lower.includes('task') ||
    lower.includes('step') ||
    lower.includes('todo') ||
    lower.includes('card') ||
    lower.includes('action item');

  if (mentionsCode) {
    return ['Can you show me the implementation?', 'Tell me more', 'Give an example'];
  }
  if (mentionsTasks) {
    return ['Create cards for these tasks', 'Tell me more', 'Summarize'];
  }
  return ['Tell me more', 'Give an example', 'Summarize'];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SmartSuggestions({ chatLevel, projectId, onSelect }: SmartSuggestionsProps) {
  const [hidden, setHidden] = useState(false);
  const [followUp, setFollowUp] = useState<string[] | null>(null);

  const project = useProjectStore((s) =>
    projectId ? s.projects.find((p) => p.id === projectId) : undefined,
  );

  const suggestions = useMemo(() => {
    if (followUp) return followUp;
    return getContextSuggestions(chatLevel, project?.name);
  }, [chatLevel, project?.name, followUp]);

  const handleSelect = useCallback(
    (text: string) => {
      onSelect(text);
      setHidden(true);
    },
    [onSelect],
  );

  return {
    element: (
      <div
        className={cn(
          'quick-replies-wrapper',
          hidden && 'opacity-0 pointer-events-none transition-opacity',
        )}
        data-testid="quick-replies"
      >
        <div className="quick-replies flex flex-wrap gap-2 px-2 py-1.5">
          {suggestions.map((text) => (
            <button
              key={text}
              type="button"
              className="quick-reply-chip px-3 py-1.5 text-sm rounded-full border border-border bg-card hover:bg-accent hover:text-accent-foreground transition-colors"
              title={text}
              onClick={() => handleSelect(text)}
            >
              {text}
            </button>
          ))}
        </div>
      </div>
    ),
    /** Called when user starts/stops typing */
    onUserTyping: (value: string) => {
      setHidden(value.length > 0);
    },
    /** Called after AI responds — show follow-up chips */
    onAiResponse: (responseContent: string) => {
      setFollowUp(getFollowUpSuggestions(responseContent));
      setHidden(false);
    },
    /** Reset to context-based suggestions */
    refresh: () => {
      setFollowUp(null);
      setHidden(false);
    },
  };
}
