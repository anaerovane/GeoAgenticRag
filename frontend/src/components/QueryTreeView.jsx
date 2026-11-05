import QueryTreeNode from './QueryTreeNode.jsx';
import { CountBadge } from './bits.jsx';

function countStatuses(node, tally = { done: 0, running: 0, pending: 0, pruned: 0, failed: 0 }) {
  if (!node) return tally;
  tally[node.status] = (tally[node.status] || 0) + 1;
  for (const child of node.children || []) countStatuses(child, tally);
  return tally;
}

export default function QueryTreeView({ tree, runningIds, results, running }) {
  const tally = tree ? countStatuses(tree) : null;

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-slate-800 bg-slate-900/70 shadow-xl shadow-black/20">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2.5">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
          Live Query Tree
        </h2>
        {tally ? (
          <div className="flex items-center gap-1">
            <CountBadge tone="emerald">{tally.done || 0} done</CountBadge>
            <CountBadge tone="sky">{tally.running || 0} running</CountBadge>
            <CountBadge>{tally.pending || 0} pending</CountBadge>
            {(tally.pruned || 0) > 0 ? <CountBadge>{tally.pruned} pruned</CountBadge> : null}
            {(tally.failed || 0) > 0 ? <CountBadge>{tally.failed} failed</CountBadge> : null}
          </div>
        ) : null}
        <span className="ml-auto font-mono text-[10px] text-slate-600">
          {running ? 'streaming tree events…' : 'source of truth: /tree frames'}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {!tree ? (
          <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-2 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full border border-dashed border-slate-700 text-xl text-slate-600">
              ⑂
            </div>
            <p className="text-xs font-medium text-slate-500">
              {running
                ? 'Planning the query tree…'
                : 'Run a question to see its query tree grow live.'}
            </p>
            <p className="max-w-[280px] text-[10px] leading-relaxed text-slate-600">
              Nodes are small tasks (sql / search / reasoning). JEV decides after each one whether
              to complete, extend, prune or fail the branch.
            </p>
          </div>
        ) : (
          <ul className="space-y-1.5">
            <QueryTreeNode node={tree} depth={0} runningIds={runningIds} results={results} />
          </ul>
        )}
      </div>
    </section>
  );
}
