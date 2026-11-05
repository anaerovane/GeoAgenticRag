/**
 * Small shared presentational bits: status pills, tool chips, JEV action
 * badges and inline evidence citation chips.
 */

const STATUS_STYLES = {
  pending: 'bg-slate-800 text-slate-400 border-slate-700',
  running: 'bg-sky-500/15 text-sky-300 border-sky-500/40 animate-pulse',
  done: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  pruned: 'bg-amber-500/10 text-amber-300/80 border-amber-500/30 line-through',
  failed: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  success: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  empty: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  error: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
};

export function StatusPill({ status }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${style}`}
    >
      {status}
    </span>
  );
}

const TOOL_META = {
  sql: { label: 'SQL', cls: 'bg-violet-500/15 text-violet-300 border-violet-500/30', icon: '▤' },
  search: { label: 'SEARCH', cls: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30', icon: '⌕' },
  none: { label: 'THINK', cls: 'bg-slate-700/60 text-slate-300 border-slate-600', icon: '◆' },
};

export function ToolChip({ tool }) {
  const meta = TOOL_META[tool] || TOOL_META.none;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${meta.cls}`}
    >
      <span aria-hidden="true">{meta.icon}</span>
      {meta.label}
    </span>
  );
}

export const ACTION_META = {
  complete: {
    label: 'COMPLETE',
    chip: 'bg-emerald-500 text-emerald-950',
    ring: 'border-emerald-500/50 bg-emerald-500/10',
    dot: 'bg-emerald-400',
    text: 'text-emerald-300',
  },
  add_child: {
    label: 'ADD CHILD',
    chip: 'bg-sky-500 text-sky-950',
    ring: 'border-sky-500/50 bg-sky-500/10',
    dot: 'bg-sky-400',
    text: 'text-sky-300',
  },
  prune: {
    label: 'PRUNE',
    chip: 'bg-amber-500 text-amber-950',
    ring: 'border-amber-500/50 bg-amber-500/10',
    dot: 'bg-amber-400',
    text: 'text-amber-300',
  },
  fail: {
    label: 'FAIL',
    chip: 'bg-rose-500 text-rose-950',
    ring: 'border-rose-500/50 bg-rose-500/10',
    dot: 'bg-rose-400',
    text: 'text-rose-300',
  },
};

export function ActionBadge({ action, size = 'md' }) {
  const meta = ACTION_META[action] || ACTION_META.complete;
  const sizeCls = size === 'sm'
    ? 'px-1.5 py-0.5 text-[9px]'
    : 'px-2.5 py-1 text-[11px]';
  return (
    <span
      className={`inline-flex items-center rounded font-black tracking-widest ${meta.chip} ${sizeCls}`}
    >
      {meta.label}
    </span>
  );
}

/** Render an [e1]-style citation found in answer text as a highlighted chip. */
export function CitedAnswer({ text }) {
  if (!text) return null;
  const parts = String(text).split(/(\[e\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = /^\[e\d+\]$/.exec(part);
        if (m) {
          return (
            <span
              key={i}
              className="mx-0.5 inline-flex items-center rounded border border-sky-500/40 bg-sky-500/15 px-1.5 py-0.5 align-baseline font-mono text-[11px] font-bold text-sky-300"
            >
              {part}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

export function CountBadge({ children, tone = 'slate' }) {
  const tones = {
    slate: 'bg-slate-800 text-slate-300 border-slate-700',
    sky: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
    emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  };
  return (
    <span
      className={`inline-flex min-w-[1.25rem] items-center justify-center rounded-full border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${tones[tone] || tones.slate}`}
    >
      {children}
    </span>
  );
}
