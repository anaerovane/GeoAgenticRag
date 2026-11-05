import { CountBadge } from './bits.jsx';

export default function Header({ health }) {
  const ok = health?.status === 'ready';
  return (
    <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1680px] items-center gap-4 px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-400 via-sky-500 to-indigo-500 font-black text-slate-950 shadow-lg shadow-sky-500/20">
            G
          </div>
          <div>
            <h1 className="text-[15px] font-bold tracking-tight text-slate-100">
              GeoAgenticRag
            </h1>
            <p className="text-[11px] font-medium tracking-wide text-slate-400">
              JEV-driven Geographic Tree-RAG
            </p>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {health?.mock ? (
            <span className="rounded-full border border-indigo-500/40 bg-indigo-500/15 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-indigo-300">
              mock mode
            </span>
          ) : null}
          <span className="flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900/80 px-3 py-1">
            <span
              className={`h-2 w-2 rounded-full ${
                ok
                  ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'
                  : 'bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.8)]'
              }`}
            />
            <span className="text-[11px] font-medium text-slate-300">
              {health ? (ok ? 'API ready' : 'API degraded') : 'connecting…'}
            </span>
          </span>
          {health?.schema_version ? (
            <CountBadge>schema {health.schema_version}</CountBadge>
          ) : null}
        </div>
      </div>
    </header>
  );
}
