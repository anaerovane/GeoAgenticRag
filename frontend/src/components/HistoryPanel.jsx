import { useState } from 'react';
import { CountBadge } from './bits.jsx';

function formatTime(epochSeconds) {
  if (!epochSeconds) return '';
  try {
    return new Date(epochSeconds * 1000).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return '';
  }
}

export default function HistoryPanel({ queries, onPick, loading }) {
  const [open, setOpen] = useState(true);
  const items = queries || [];

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-slate-800 bg-slate-900/70">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
      >
        <span className="text-slate-600">{open ? '▾' : '▸'}</span>
        <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
          History
        </h2>
        <CountBadge tone="sky">{items.length}</CountBadge>
        <span className="ml-auto font-mono text-[10px] text-slate-600">
          GET /api/v1/history
        </span>
      </button>

      {open && (
        <div className="min-h-0 flex-1 overflow-y-auto border-t border-slate-800">
          {loading && items.length === 0 ? (
            <p className="px-4 py-3 text-xs text-slate-500">Loading…</p>
          ) : items.length === 0 ? (
            <p className="px-4 py-3 text-xs text-slate-500">
              No queries yet. Run one to see it here.
            </p>
          ) : (
            <ul className="divide-y divide-slate-800/70">
              {items.map((q) => (
                <li key={q.query_id}>
                  <button
                    type="button"
                    onClick={() => onPick(q)}
                    className="group block w-full px-4 py-2.5 text-left transition hover:bg-slate-800/50"
                  >
                    <div className="flex items-baseline gap-2">
                      <p className="flex-1 truncate text-xs text-slate-300 group-hover:text-sky-300">
                        {q.question}
                      </p>
                      <span className="shrink-0 font-mono text-[10px] text-slate-600">
                        {q.elapsed_ms != null ? `${q.elapsed_ms}ms` : ''}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="font-mono text-[9px] text-slate-600">
                        {String(q.query_id || '').slice(0, 8)}
                      </span>
                      <span className="text-[9px] text-slate-600">
                        {formatTime(q.created_at)}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
