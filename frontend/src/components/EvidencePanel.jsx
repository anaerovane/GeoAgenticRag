import { useMemo, useState } from 'react';
import { CountBadge, ToolChip } from './bits.jsx';

const SOURCE_META = {
  sql: { label: 'sql', cls: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  search: { label: 'search', cls: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30' },
  tool: { label: 'tool', cls: 'bg-slate-700/60 text-slate-300 border-slate-600' },
};

function SourceChip({ source }) {
  const meta = SOURCE_META[source] || SOURCE_META.tool;
  return (
    <span
      className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

function EvidenceCard({ item }) {
  return (
    <li className="animate-fade-up rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2.5 transition-colors hover:border-slate-700">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-5 min-w-[2rem] items-center justify-center rounded border border-sky-500/40 bg-sky-500/15 px-1.5 font-mono text-[10px] font-bold text-sky-300">
          [{item.id}]
        </span>
        <SourceChip source={item.source} />
        <span className="font-mono text-[9px] text-slate-500">node {item.node_id}</span>
        {item.score ? (
          <span className="ml-auto font-mono text-[9px] text-slate-600">
            score {Number(item.score).toFixed(3)}
          </span>
        ) : null}
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-slate-300">
        {item.text || <span className="italic text-slate-600">(empty text)</span>}
      </p>
    </li>
  );
}

export default function EvidencePanel({ evidence, count }) {
  const [filterNode, setFilterNode] = useState('all');
  const items = evidence || [];

  const nodeIds = useMemo(() => {
    const ids = [];
    for (const item of items) {
      if (item.node_id && !ids.includes(item.node_id)) ids.push(item.node_id);
    }
    return ids;
  }, [items]);

  const visible = filterNode === 'all'
    ? items
    : items.filter((i) => i.node_id === filterNode);

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-slate-800 bg-slate-900/70">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2.5">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
          Evidence
        </h2>
        <CountBadge tone="sky">{count ?? items.length}</CountBadge>
        {nodeIds.length > 1 ? (
          <select
            value={filterNode}
            onChange={(e) => setFilterNode(e.target.value)}
            className="ml-auto rounded border border-slate-700 bg-slate-800 px-1.5 py-1 font-mono text-[10px] text-slate-300 outline-none"
          >
            <option value="all">all nodes</option>
            {nodeIds.map((id) => (
              <option key={id} value={id}>
                node {id}
              </option>
            ))}
          </select>
        ) : (
          <span className="ml-auto font-mono text-[10px] text-slate-600">
            survives branch pruning
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {items.length === 0 ? (
          <p className="px-1 py-4 text-center text-xs text-slate-500">
            No evidence recorded yet. Observations from every branch land here.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {visible.map((item) => (
              <EvidenceCard key={item.id} item={item} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
