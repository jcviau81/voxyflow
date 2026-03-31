import type { Card, ActivityEntry } from '../../types';

const STATUS_CONFIG = [
  { key: 'idea' as const,        label: '💡 Idea',       color: '#a78bfa' },
  { key: 'todo' as const,        label: '📋 Todo',        color: '#60a5fa' },
  { key: 'in-progress' as const, label: '🔨 In Progress', color: '#fbbf24' },
  { key: 'done' as const,        label: '✅ Done',         color: '#4ade80' },
];

const PRIORITY_CONFIG = [
  { value: 3, label: '🔴 Critical', color: '#ef4444' },
  { value: 2, label: '🟠 High',     color: '#f97316' },
  { value: 1, label: '🟡 Medium',   color: '#eab308' },
  { value: 0, label: '🟢 Low',      color: '#22c55e' },
];

const AGENT_COLORS: Record<string, string> = {
  general:    '#ff6b6b',
  coder:      '#60a5fa',
  architect:  '#a78bfa',
  researcher: '#34d399',
  designer:   '#f472b6',
  writer:     '#fb923c',
  qa:         '#fbbf24',
  unassigned: '#5c5c6b',
};

function StatCard({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-card border border-border rounded-xl p-5 flex flex-col gap-3 transition-colors hover:border-white/[0.12] ${className}`}>
      {children}
    </div>
  );
}

function StatCardTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[0.8125rem] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
      {children}
    </div>
  );
}

interface BarRowProps {
  label: string;
  count: number;
  pct: number;
  color: string;
}

function BarRow({ label, count, pct, color }: BarRowProps) {
  return (
    <div className="grid grid-cols-[130px_1fr_28px] items-center gap-2">
      <div className="text-xs text-muted-foreground truncate">{label}</div>
      <div className="h-2 bg-white/[0.06] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full min-w-[2px] transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <div className="text-[0.8125rem] font-semibold text-muted-foreground text-right">{count}</div>
    </div>
  );
}

interface ProgressRingProps { cards: Card[] }

function ProgressRing({ cards }: ProgressRingProps) {
  const total = cards.length;
  const done = cards.filter(c => c.status === 'done').length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <StatCard className="items-center">
      <StatCardTitle>Progress</StatCardTitle>
      <div className="flex items-center justify-center">
        <svg viewBox="0 0 120 120" width="120" height="120">
          <circle cx="60" cy="60" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="10" />
          <circle
            cx="60" cy="60" r={radius}
            fill="none" stroke="#4ade80" strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            transform="rotate(-90 60 60)"
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
          />
          <text x="60" y="60" textAnchor="middle" dominantBaseline="middle"
            fill="#e8e8ed" fontSize="20" fontWeight="700">
            {pct}%
          </text>
        </svg>
      </div>
      <div className="text-xs text-muted-foreground text-center">{done} of {total} cards done</div>
    </StatCard>
  );
}

function StatusChart({ cards }: { cards: Card[] }) {
  const total = cards.length || 1;
  return (
    <StatCard>
      <StatCardTitle>Cards by Status</StatCardTitle>
      <div className="flex flex-col gap-2.5">
        {STATUS_CONFIG.map(cfg => {
          const count = cards.filter(c => c.status === cfg.key).length;
          const pct = Math.round((count / total) * 100);
          return <BarRow key={cfg.key} label={cfg.label} count={count} pct={pct} color={cfg.color} />;
        })}
      </div>
    </StatCard>
  );
}

function PriorityChart({ cards }: { cards: Card[] }) {
  const total = cards.length || 1;
  return (
    <StatCard>
      <StatCardTitle>Cards by Priority</StatCardTitle>
      <div className="flex flex-col gap-2.5">
        {PRIORITY_CONFIG.map(cfg => {
          const count = cards.filter(c => c.priority === cfg.value).length;
          const pct = Math.round((count / total) * 100);
          return <BarRow key={cfg.value} label={cfg.label} count={count} pct={pct} color={cfg.color} />;
        })}
      </div>
    </StatCard>
  );
}

function AgentChart({ cards }: { cards: Card[] }) {
  const agentCounts: Record<string, number> = {};
  for (const c of cards) {
    const agent = c.agentType || c.assignedAgent || 'unassigned';
    agentCounts[agent] = (agentCounts[agent] || 0) + 1;
  }
  const sorted = Object.entries(agentCounts).sort((a, b) => b[1] - a[1]);
  const total = cards.length || 1;

  return (
    <StatCard>
      <StatCardTitle>Cards by Agent</StatCardTitle>
      <div className="flex flex-col gap-2.5">
        {sorted.length === 0 ? (
          <div className="text-xs text-muted-foreground py-1">No agents assigned yet.</div>
        ) : sorted.map(([agent, count]) => {
          const pct = Math.round((count / total) * 100);
          const color = AGENT_COLORS[agent] || '#9e9ea8';
          const label = agent === 'unassigned'
            ? '— Unassigned'
            : `🤖 ${agent.charAt(0).toUpperCase() + agent.slice(1)}`;
          return <BarRow key={agent} label={label} count={count} pct={pct} color={color} />;
        })}
      </div>
    </StatCard>
  );
}

function VelocityCard({ activities }: { activities: ActivityEntry[] }) {
  const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const doneRecently = activities.filter(
    a => a.type === 'card_moved' &&
         a.message.includes('✅ Done') &&
         a.timestamp >= sevenDaysAgo,
  );

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days: { label: string; count: number }[] = [];
  for (let i = 6; i >= 0; i--) {
    const dayStart = today.getTime() - i * 86400000;
    const dayEnd = dayStart + 86400000;
    const count = doneRecently.filter(a => a.timestamp >= dayStart && a.timestamp < dayEnd).length;
    const d = new Date(dayStart);
    days.push({ label: d.toLocaleDateString('en', { weekday: 'short' }), count });
  }
  const maxCount = Math.max(...days.map(d => d.count), 1);

  return (
    <StatCard>
      <StatCardTitle>Velocity (last 7 days)</StatCardTitle>
      <div className="text-5xl font-extrabold text-foreground leading-none text-center">
        {doneRecently.length}
      </div>
      <div className="text-xs text-muted-foreground text-center">
        {doneRecently.length === 1 ? 'card completed' : 'cards completed'}
      </div>
      <div className="flex items-end gap-1.5 h-14 pt-2">
        {days.map((day, i) => (
          <div key={i} className="flex flex-col items-center flex-1 gap-1">
            <div
              className="w-full rounded-t-[3px] min-h-[2px] transition-all duration-500"
              style={{
                height: `${Math.round((day.count / maxCount) * 40)}px`,
                background: 'var(--color-accent)',
              }}
              title={`${day.label}: ${day.count}`}
            />
            <div className="text-[0.8125rem] text-muted-foreground uppercase">
              {day.label.slice(0, 1)}
            </div>
          </div>
        ))}
      </div>
    </StatCard>
  );
}

function FocusTimeCard({ focusAnalytics }: {
  focusAnalytics: { total_sessions: number; total_minutes: number } | null;
}) {
  return (
    <StatCard>
      <StatCardTitle>⏱ Focus Time</StatCardTitle>
      {focusAnalytics ? (
        <>
          <div className="text-5xl font-extrabold text-foreground leading-none text-center">
            {focusAnalytics.total_minutes >= 60
              ? `${Math.floor(focusAnalytics.total_minutes / 60)}h ${focusAnalytics.total_minutes % 60}m`
              : `${focusAnalytics.total_minutes}m`}
          </div>
          <div className="text-xs text-muted-foreground text-center">
            {focusAnalytics.total_sessions} sessions total
          </div>
        </>
      ) : (
        <>
          <div className="text-5xl font-extrabold text-muted-foreground leading-none text-center">—</div>
          <div className="text-xs text-muted-foreground text-center">No focus sessions yet</div>
        </>
      )}
    </StatCard>
  );
}

interface StatsGridProps {
  cards: Card[];
  activities: ActivityEntry[];
  focusAnalytics: { total_sessions: number; total_minutes: number } | null;
}

export function StatsGrid({ cards, activities, focusAnalytics }: StatsGridProps) {
  return (
    <div className="grid grid-cols-2 gap-4 max-[700px]:grid-cols-1">
      <ProgressRing cards={cards} />
      <StatusChart cards={cards} />
      <PriorityChart cards={cards} />
      <AgentChart cards={cards} />
      <VelocityCard activities={activities} />
      <FocusTimeCard focusAnalytics={focusAnalytics} />
    </div>
  );
}
