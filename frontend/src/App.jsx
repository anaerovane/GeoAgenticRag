import { useCallback, useEffect, useState } from 'react';
import Header from './components/Header.jsx';
import QueryComposer from './components/QueryComposer.jsx';
import JevDecisionTimeline from './components/JevDecisionTimeline.jsx';
import QueryTreeView from './components/QueryTreeView.jsx';
import EvidencePanel from './components/EvidencePanel.jsx';
import AnswerCard from './components/AnswerCard.jsx';
import HistoryPanel from './components/HistoryPanel.jsx';
import { useQueryRun } from './hooks/useQueryRun.js';
import { getDatasets, getHealth, getHistory } from './api/client.js';

export default function App() {
  const [health, setHealth] = useState(null);
  const [datasetList, setDatasetList] = useState([]);
  const [datasetId, setDatasetId] = useState(null);
  const [question, setQuestion] = useState('Which parks are in the West End?');
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const { state, run, stop, reset } = useQueryRun();
  const { running, tree, decisions, evidence, evidenceCount, answer, error } = state;

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(setHealth)
      .catch(() => setHealth(null));
    getDatasets(controller.signal)
      .then((data) => {
        const ids = data?.datasets || [];
        setDatasetList(ids);
        setDatasetId((prev) => prev || data?.default || ids[0] || null);
      })
      .catch(() => setDatasetList([]));
    return () => controller.abort();
  }, []);

  const refreshHistory = useCallback(() => {
    setHistoryLoading(true);
    getHistory(50)
      .then((data) => setHistory(data?.queries || []))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, []);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  // Keep the history panel fresh after a run finishes.
  useEffect(() => {
    if (state.done) refreshHistory();
  }, [state.done, refreshHistory]);

  const handleRun = useCallback(() => {
    const q = question.trim();
    if (!q || running) return;
    run(q, datasetId);
  }, [question, running, datasetId, run]);

  return (
    <div className="flex min-h-screen flex-col lg:h-screen lg:overflow-hidden">
      <Header health={health} />

      <main
        className="mx-auto grid w-full max-w-[1760px] flex-1 grid-cols-1 gap-4 p-4 lg:min-h-0 lg:grid-cols-[minmax(330px,1.5fr)_minmax(400px,1.9fr)_minmax(440px,2.2fr)]"
      >
        {/* Column 1 — query composer + run history */}
        <div className="flex flex-col gap-4 lg:min-h-0">
          <QueryComposer
            question={question}
            onQuestionChange={setQuestion}
            datasets={datasetList}
            datasetId={datasetId}
            onDatasetChange={setDatasetId}
            running={running}
            onRun={handleRun}
            onStop={stop}
            onReset={reset}
          />
          <div className="flex min-h-0 flex-1 flex-col">
            <HistoryPanel
              queries={history}
              loading={historyLoading}
              onPick={(q) => setQuestion(q.question)}
            />
          </div>
        </div>

        {/* Column 2 — JEV decision timeline (visual centerpiece) */}
        <div className="relative flex min-h-[480px] flex-col lg:min-h-0">
          <div className="pointer-events-none absolute -inset-px rounded-xl bg-gradient-to-b from-sky-500/25 via-emerald-500/10 to-transparent" />
          <div className="relative flex min-h-0 flex-1 flex-col">
            <JevDecisionTimeline decisions={decisions} running={running} />
          </div>
        </div>

        {/* Column 3 — live tree + evidence + answer */}
        <div className="flex min-h-[480px] flex-col gap-4 lg:min-h-0">
          <div className="flex min-h-0 flex-[1.5] flex-col">
            <QueryTreeView
              tree={tree}
              runningIds={state.runningNodes}
              results={state.nodeResults}
              running={running}
            />
          </div>
          <div className="flex min-h-0 flex-1 flex-col">
            <EvidencePanel evidence={evidence} count={evidenceCount} />
          </div>
          <div className="flex max-h-[42%] flex-col overflow-y-auto">
            <AnswerCard
              answer={answer}
              error={error}
              elapsedMs={state.elapsedMs}
              nodeCounts={state.nodeCounts}
              models={state.models}
              evidenceCount={evidenceCount}
              done={state.done && !error}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
