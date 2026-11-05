import { StatusPill, ToolChip, ActionBadge } from './bits.jsx';

function truncate(text, n = 120) {
  const s = String(text || '');
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function ResultLine({ node, overlay }) {
  const result = node.result || overlay || null;
  if (!result) return null;
  const tone =
    result.status === 'success'
      ? 'text-emerald-300/90'
      : result.status === 'empty'
        ? 'text-amber-300/90'
        : 'text-rose-300/90';
  return (
    <p className={`mt-1 text-[11px] leading-relaxed ${tone}`}>
      <span className="font-semibold uppercase tracking-wider">{result.status}</span>
      {result.summary ? ` · ${truncate(result.summary, 160)}` : ''}
      {result.error ? ` · ${truncate(result.error, 120)}` : ''}
    </p>
  );
}

function DecisionLine({ decision }) {
  if (!decision) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <span className="text-[9px] font-bold uppercase tracking-widest text-slate-500">
        jev
      </span>
      <ActionBadge action={decision.action} size="sm" />
      <span className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
        route: {decision.route_id}
      </span>
      {decision.follow_up?.query ? (
        <span className="truncate text-[10px] italic text-sky-300/80">
          → “{truncate(decision.follow_up.query, 70)}”
        </span>
      ) : null}
    </div>
  );
}

export default function QueryTreeNode({ node, depth = 0, runningIds = [], results = {} }) {
  const isRunning = runningIds.includes(node.id);
  const status = isRunning && node.status === 'pending' ? 'running' : node.status;
  const overlay = results[node.id];
  const indent = depth * 20;

  return (
    <li className="relative">
      {depth > 0 && (
        <>
          <span
            className="absolute top-0 bottom-0 w-px bg-slate-800"
            style={{ left: `${(depth - 1) * 20 + 7}px` }}
          />
          <span
            className="absolute top-[13px] h-px w-3.5 bg-slate-800"
            style={{ left: `${(depth - 1) * 20 + 7}px` }}
          />
        </>
      )}
      <div
        className={`rounded-lg border px-3 py-2 transition-colors ${
          status === 'running'
            ? 'border-sky-500/50 bg-sky-500/[0.07]'
            : status === 'failed'
              ? 'border-rose-500/40 bg-rose-500/[0.06]'
              : status === 'pruned'
                ? 'border-slate-800 bg-slate-900/40 opacity-70'
                : 'border-slate-800 bg-slate-900/60 hover:border-slate-700'
        }`}
        style={{ marginLeft: indent }}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[10px] font-bold text-slate-400">{node.id}</span>
          <ToolChip tool={node.tool} />
          <StatusPill status={status} />
          {node.when && node.when !== 'always' ? (
            <span className="rounded border border-slate-700/80 px-1.5 py-0.5 font-mono text-[9px] text-slate-500">
              when: {node.when}
            </span>
          ) : null}
        </div>

        <p
          className={`mt-1 text-[12px] leading-relaxed ${
            status === 'pruned' ? 'text-slate-500 line-through' : 'text-slate-200'
          }`}
          title={node.query}
        >
          {truncate(node.query, 140)}
        </p>

        <ResultLine node={node} overlay={overlay} />
        <DecisionLine decision={node.decision} />
      </div>

      {node.children && node.children.length > 0 ? (
        <ul className="mt-1.5 space-y-1.5">
          {node.children.map((child) => (
            <QueryTreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              runningIds={runningIds}
              results={results}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
