// Agent Personas (legacy, used by old assignedAgent field)
export const AGENT_PERSONAS: Record<string, { name: string; emoji: string; description: string }> = {
  coder: { name: 'Coder', emoji: '👩‍💻', description: 'Code implementation & debugging' },
  architect: { name: 'Architect', emoji: '🏗️', description: 'System design & architecture' },
  designer: { name: 'Designer', emoji: '🎨', description: 'UI/UX design & styling' },
  devops: { name: 'DevOps', emoji: '⚙️', description: 'Infrastructure & deployment' },
  analyst: { name: 'Analyst', emoji: '📊', description: 'Requirements & analysis' },
  tester: { name: 'Tester', emoji: '🧪', description: 'Testing & quality assurance' },
  writer: { name: 'Writer', emoji: '📝', description: 'Documentation & specs' },
};

// Agent type → emoji mapping (general is the default, not selectable)
export const AGENT_TYPE_EMOJI: Record<string, string> = {
  researcher: '🔍',
  coder: '💻',
  designer: '🎨',
  architect: '🏗️',
  writer: '✍️',
  qa: '🧪',
};
