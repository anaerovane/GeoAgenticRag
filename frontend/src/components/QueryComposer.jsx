import { useState } from 'react';

const EXAMPLES = [
  'Which parks are in the West End?',
  'Find highly rated cafes near Downtown',
  'What is the highest rated restaurant in the city?',
  'How many museums are in the Lakefront district?',
];

export default function QueryComposer({
  question,
  onQuestionChange,
  datasets,
  datasetId,
  onDatasetChange,
  running,
  onRun,
  onStop,
  onReset,
}) {
  const [focused, setFocused] = useState(false);
  const canRun = !running && question.trim().length > 0;

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/70 shadow-xl shadow-black/20">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
          Query Composer
        </h2>
        <span className="font-mono text-[10px] text-slate-500">
          POST /api/v1/query/stream
        </span>
      </div>

      <div className="space-y-3 p-4">
        <div className="flex items-center gap-2">
          <label
            htmlFor="dataset-select"
            className="text-[11px] font-semibold uppercase tracking-wider text-slate-500"
          >
            Dataset
          </label>
          <select
            id="dataset-select"
            value={datasetId || ''}
            onChange={(e) => onDatasetChange(e.target.value || null)}
            disabled={running}
            className="rounded-md border border-slate-700 bg-slate-800 px-2.5 py-1.5 font-mono text-xs text-slate-200 outline-none transition focus:border-sky-500 focus:ring-1 focus:ring-sky-500/40 disabled:opacity-50"
          >
            {(datasets || []).length === 0 ? (
              <option value="">no datasets</option>
            ) : (
              (datasets || []).map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))
            )}
          </select>
        </div>

        <div
          className={`rounded-lg border transition-colors ${
            focused ? 'border-sky-500/60 ring-2 ring-sky-500/20' : 'border-slate-700'
          }`}
        >
          <textarea
            value={question}
            onChange={(e) => onQuestionChange(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canRun) {
                e.preventDefault();
                onRun();
              }
            }}
            rows={3}
            placeholder="Ask a geographic question… (⌘/Ctrl + Enter to run)"
            className="w-full resize-none rounded-lg bg-transparent px-3.5 py-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none"
          />
          <div className="flex items-center gap-2 border-t border-slate-800 px-3 py-2">
            {running ? (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/50 bg-rose-500/15 px-3 py-1.5 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/25"
              >
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" />
                Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={onRun}
                disabled={!canRun}
                className="inline-flex items-center gap-1.5 rounded-md bg-gradient-to-r from-emerald-500 to-sky-500 px-4 py-1.5 text-xs font-bold text-slate-950 shadow-lg shadow-sky-500/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
              >
                ▶ Run
              </button>
            )}
            <button
              type="button"
              onClick={onReset}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
            >
              Reset
            </button>
            <span className="ml-auto font-mono text-[10px] text-slate-600">
              {question.trim().length}/4000
            </span>
          </div>
        </div>

        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-600">
            Try an example
          </p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                disabled={running}
                onClick={() => onQuestionChange(ex)}
                className="rounded-full border border-slate-700/80 bg-slate-800/60 px-2.5 py-1 text-[11px] text-slate-400 transition hover:border-sky-500/40 hover:text-sky-300 disabled:opacity-40"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
