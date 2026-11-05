import { CitedAnswer, CountBadge, ToolChip } from './bits.jsx';

function ErrorCard({ error }) {
  return (
    <div className="animate-fade-up rounded-xl border border-rose-500/40 bg-rose-500/[0.08] p-4">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-rose-500 font-black text-rose-950">
          !
        </span>
        <h3 className="text-[12px] font-bold uppercase tracking-widest text-rose-300">
          Run failed
        </h3>
        {error.stage ? (
          <span className="rounded border border-rose-500/40 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">
            stage: {error.stage}
          </span>
        ) : null}
        {error.node_id ? (
          <span className="font-mono text-[10px] text-rose-300/80">node {error.node_id}</span>
        ) : null}
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-rose-200">
        {error.message || 'Unknown error'}
      </p>
    </div>
  );
}

export default function AnswerCard({ answer, error, elapsedMs, nodeCounts, models, evidenceCount, done }) {
  if (error) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
        <ErrorCard error={error} />
      </section>
    );
  }

  if (!answer) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/70">
        <div className="border-b border-slate-800 px-4 py-2.5">
          <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
            Answer
          </h2>
        </div>
        <p className="px-4 py-6 text-center text-xs text-slate-500">
          The synthesized answer — citing only recorded evidence — will appear here.
        </p>
      </section>
    );
  }

  const countEntries = nodeCounts
    ? Object.entries(nodeCounts).filter(([, v]) => v > 0)
    : [];

  return (
    <section className="animate-fade-up overflow-hidden rounded-xl border border-emerald-500/30 bg-slate-900/70 shadow-xl shadow-emerald-500/5">
      <div className="flex items-center gap-2 border-b border-emerald-500/20 bg-gradient-to-r from-emerald-500/10 to-transparent px-4 py-2.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-400 text-[11px] font-black text-emerald-950">
          ✓
        </span>
        <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-emerald-300">
          Answer
        </h2>
        {done ? (
          <span className="ml-auto rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest text-emerald-300">
            complete
          </span>
        ) : null}
      </div>

      <div className="px-4 py-3.5">
        <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-100">
          <CitedAnswer text={answer} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-slate-800 bg-slate-950/40 px-4 py-2.5">
        {elapsedMs != null ? (
          <span className="font-mono text-[10px] text-slate-400">
            <span className="text-slate-600">elapsed</span> {elapsedMs} ms
          </span>
        ) : null}
        {evidenceCount != null ? (
          <span className="font-mono text-[10px] text-slate-400">
            <span className="text-slate-600">evidence</span> {evidenceCount}
          </span>
        ) : null}
        {countEntries.length > 0 ? (
          <span className="flex items-center gap-1">
            <span className="font-mono text-[10px] text-slate-600">nodes</span>
            {countEntries.map(([k, v]) => (
              <CountBadge key={k} tone={k === 'done' ? 'emerald' : k === 'failed' ? 'slate' : 'sky'}>
                {v} {k}
              </CountBadge>
            ))}
          </span>
        ) : null}
        {models?.planner || models?.jev ? (
          <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-slate-500">
            <span className="text-slate-600">models</span>
            {models.planner ? <span>planner:{models.planner}</span> : null}
            {models.jev ? <span>jev:{models.jev}</span> : null}
          </span>
        ) : null}
      </div>
    </section>
  );
}
