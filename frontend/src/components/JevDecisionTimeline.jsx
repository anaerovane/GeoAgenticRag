import { useEffect, useRef } from 'react';
import { ActionBadge, ACTION_META, ToolChip, CountBadge } from './bits.jsx';

function DecisionCard({ d }) {
  const meta = ACTION_META[d.action] || ACTION_META.complete;
  return (
    <li className="animate-jev-in relative pl-9">
      {/* connector line + glowing node dot */}
      <span
        className={`absolute left-[13px] top-1 h-3.5 w-3.5 rounded-full border-2 border-slate-950 ${meta.dot} shadow-[0_0_10px_currentColor]`}
        style={{ color: 'inherit' }}
      />
      <span className="absolute left-[19px] top-6 bottom-[-14px] w-px bg-gradient-to-b from-slate-700 to-transparent" />

      <div className={`rounded-lg border ${meta.ring} px-3.5 py-2.5`}>
        <div className="flex flex-wrap items-center gap-2">
          <ActionBadge action={d.action} />
          <span className="rounded border border-slate-700 bg-slate-900/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-300">
            route: {d.route_id}
          </span>
          <span className="font-mono text-[10px] text-slate-500">node {d.node_id}</span>
          <span className="ml-auto rounded-full bg-slate-950/60 px-1.5 py-0.5 font-mono text-[9px] text-slate-500">
            #{d.seq}
          </span>
        </div>

        <p className="mt-2 text-[12px] leading-relaxed text-slate-200">
          {d.reason || <span className="italic text-slate-500">no reason given</span>}
        </p>

        {d.follow_up && (d.follow_up.query || d.follow_up.tool) ? (
          <div className="mt-2 rounded-md border border-sky-500/30 bg-sky-500/10 px-2.5 py-2">
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-bold uppercase tracking-widest text-sky-400">
                follow-up
              </span>
              {d.follow_up.tool ? <ToolChip tool={d.follow_up.tool} /> : null}
            </div>
            <p className="mt-1 text-[11px] italic leading-relaxed text-sky-200">
              “{d.follow_up.query}”
            </p>
          </div>
        ) : null}

        {d.model ? (
          <p className="mt-2 font-mono text-[9px] text-slate-500">model: {d.model}</p>
        ) : null}
      </div>
    </li>
  );
}

export default function JevDecisionTimeline({ decisions, running }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [decisions.length]);

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-slate-800 bg-slate-900/70 shadow-xl shadow-black/20">
      {/* centerpiece header */}
      <div className="relative overflow-hidden rounded-t-xl border-b border-slate-800 bg-gradient-to-r from-slate-900 via-slate-900 to-slate-900 px-4 py-3">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,rgba(56,189,248,0.18),transparent_55%),radial-gradient(ellipse_at_bottom_right,rgba(16,185,129,0.16),transparent_55%)]" />
        <div className="relative flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-emerald-400 to-sky-500 font-black text-slate-950">
            J
          </span>
          <div>
            <h2 className="text-[13px] font-black uppercase tracking-[0.22em] text-slate-100">
              JEV Decision Timeline
            </h2>
            <p className="text-[10px] font-medium tracking-wide text-slate-400">
              every branch verdict — complete · add_child · prune · fail
            </p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <CountBadge tone="emerald">{decisions.filter((d) => d.action === 'complete').length}</CountBadge>
            <CountBadge tone="sky">{decisions.filter((d) => d.action === 'add_child').length}</CountBadge>
            <CountBadge>{decisions.filter((d) => d.action === 'prune').length}</CountBadge>
            <CountBadge tone="slate">{decisions.filter((d) => d.action === 'fail').length}</CountBadge>
          </div>
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {decisions.length === 0 ? (
          <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-2 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full border border-dashed border-slate-700 text-xl text-slate-600">
              ⧖
            </div>
            <p className="text-xs font-medium text-slate-500">
              {running
                ? 'Waiting for the first JEV verdict…'
                : 'JEV decisions will appear here as branches resolve.'}
            </p>
            <p className="max-w-[260px] text-[10px] leading-relaxed text-slate-600">
              After every branch result, JEV emits one constrained decision that mutates the
              query tree.
            </p>
          </div>
        ) : (
          <ol className="space-y-3.5">
            {decisions.map((d) => (
              <DecisionCard key={`${d.seq}-${d.node_id}`} d={d} />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
