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

interface BarRowProps {
  label: string;
  count: number;
  pct: number;
  color: string;
}

function BarRow({ label, count, pct, color }: BarRowProps) {
  return (
    <div className="bar">
      <div className="bar-label">{label}</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="bar-count">{count}</div>
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
    <div className="stat-card progress-ring-card">
      <div className="stat-card-title">Progress</div>
      <div className="progress-ring">
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
      <div className="stat-card-sub">{done} of {total} cards done</div>
    </div>
  );
}

interface StatusChartProps { cards: Card[] }

function StatusChart({ cards }: StatusChartProps) {
  const total = cards.length || 1;
  return (
    <div className="stat-card">
      <div className="stat-card-title">Cards by Status</div>
      <div className="bar-chart">
        {STATUS_CONFIG.map(cfg => {
          const count = cards.filter(c => c.status === cfg.key).length;
          const pct = Math.round((count / total) * 100);
          return <BarRow key={cfg.key} label={cfg.label} count={count} pct={pct} color={cfg.color} />;
        })}
      </div>
    </div>
  );
}

interface PriorityChartProps { cards: Card[] }

function PriorityChart({ cards }: PriorityChartProps) {
  const total = cards.length || 1;
  return (
    <div className="stat-card">
      <div className="stat-card-title">Cards by Priority</div>
      <div className="bar-chart">
        {PRIORITY_CONFIG.map(cfg => {
          const count = cards.filter(c => c.priority === cfg.value).length;
          const pct = Math.round((count / total) * 100);
          return <BarRow key={cfg.value} label={cfg.label} count={count} pct={pct} color={cfg.color} />;
        })}
      </div>
    </div>
  );
}

interface AgentChartProps { cards: Card[] }

function AgentChart({ cards }: AgentChartProps) {
  const agentCounts: Record<string, number> = {};
  for (const c of cards) {
    const agent = c.agentType || c.assignedAgent || 'unassigned';
    agentCounts[agent] = (agentCounts[agent] || 0) + 1;
  }
  const sorted = Object.entries(agentCounts).sort((a, b) => b[1] - a[1]);
  const total = cards.length || 1;

  return (
    <div className="stat-card">
      <div className="stat-card-title">Cards by Agent</div>
      <div className="bar-chart">
        {sorted.length === 0 ? (
          <div className="stat-empty-row">No agents assigned yet.</div>
        ) : sorted.map(([agent, count]) => {
          const pct = Math.round((count / total) * 100);
          const color = AGENT_COLORS[agent] || '#9e9ea8';
          const label = agent === 'unassigned'
            ? '— Unassigned'
            : `🤖 ${agent.charAt(0).toUpperCase() + agent.slice(1)}`;
          return <BarRow key={agent} label={label} count={count} pct={pct} color={color} />;
        })}
      </div>
    </div>
  );
}

interface VelocityCardProps { activities: ActivityEntry[] }

function VelocityCard({ activities }: VelocityCardProps) {
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
    <div className="stat-card">
      <div className="stat-card-title">Velocity (last 7 days)</div>
      <div className="stat-big-number">{doneRecently.length}</div>
      <div className="stat-card-sub">
        {doneRecently.length === 1 ? 'card completed' : 'cards completed'}
      </div>
      <div className="sparkline">
        {days.map((day, i) => (
          <div key={i} className="sparkline-bar-wrap">
            <div
              className="sparkline-bar"
              style={{ height: `${Math.round((day.count / maxCount) * 40)}px` }}
              title={`${day.label}: ${day.count}`}
            />
            <div className="sparkline-label">{day.label.slice(0, 1)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface FocusTimeCardProps {
  focusAnalytics: {
    total_sessions: number;
    total_minutes: number;
  } | null;
}

function FocusTimeCard({ focusAnalytics }: FocusTimeCardProps) {
  return (
    <div className="stat-card">
      <div className="stat-card-title">⏱ Focus Time</div>
      {focusAnalytics ? (
        <>
          <div className="stat-big-number">
            {focusAnalytics.total_minutes >= 60
              ? `${Math.floor(focusAnalytics.total_minutes / 60)}h ${focusAnalytics.total_minutes % 60}m`
              : `${focusAnalytics.total_minutes}m`}
          </div>
          <div className="stat-card-sub">{focusAnalytics.total_sessions} sessions total</div>
        </>
      ) : (
        <>
          <div className="stat-big-number stat-muted">—</div>
          <div className="stat-card-sub">No focus sessions yet</div>
        </>
      )}
    </div>
  );
}

interface StatsGridProps {
  cards: Card[];
  activities: ActivityEntry[];
  focusAnalytics: { total_sessions: number; total_minutes: number } | null;
}

export function StatsGrid({ cards, activities, focusAnalytics }: StatsGridProps) {
  return (
    <div className="stats-grid">
      <ProgressRing cards={cards} />
      <StatusChart cards={cards} />
      <PriorityChart cards={cards} />
      <AgentChart cards={cards} />
      <VelocityCard activities={activities} />
      <FocusTimeCard focusAnalytics={focusAnalytics} />
    </div>
  );
}
