import { useCallback, useReducer, useRef } from 'react';
import { getArtifact, streamQuery } from '../api/client.js';

const initialState = {
  running: false,
  question: '',
  queryId: null,
  tree: null,
  decisions: [], // JEV timeline entries, in arrival order
  evidence: [], // accumulated evidence items (deduped by id)
  evidenceCount: 0,
  answer: null,
  error: null,
  done: false,
  elapsedMs: null,
  models: null,
  nodeCounts: null,
  runningNodes: [], // node ids currently executing (overlay on tree)
  nodeResults: {}, // node_id -> partial BranchResult from node_result events
};

function reducer(state, action) {
  switch (action.type) {
    case 'reset':
      return { ...initialState };
    case 'run_start':
      return { ...initialState, running: true, question: action.question };
    case 'query_started':
      return { ...state, queryId: action.data.query_id || state.queryId };
    case 'tree':
      return {
        ...state,
        tree: action.data.tree,
        // A fresh tree snapshot supersedes the running overlay for known nodes.
        runningNodes: state.runningNodes.filter((id) => {
          const n = findNode(action.data.tree, id);
          return n && (n.status === 'pending' || n.status === 'running');
        }),
      };
    case 'node_start': {
      const id = action.data.node_id;
      return {
        ...state,
        runningNodes: state.runningNodes.includes(id)
          ? state.runningNodes
          : [...state.runningNodes, id],
      };
    }
    case 'node_result': {
      const { node_id, ...result } = action.data;
      return {
        ...state,
        runningNodes: state.runningNodes.filter((id) => id !== node_id),
        nodeResults: { ...state.nodeResults, [node_id]: result },
      };
    }
    case 'jev_decision':
      return {
        ...state,
        decisions: [
          ...state.decisions,
          { seq: state.decisions.length + 1, ...action.data },
        ],
      };
    case 'evidence': {
      const seen = new Set(state.evidence.map((e) => e.id));
      const fresh = (action.data.items || []).filter((e) => e && e.id && !seen.has(e.id));
      return {
        ...state,
        evidence: [...state.evidence, ...fresh],
        evidenceCount: action.data.count ?? state.evidence.length + fresh.length,
      };
    }
    case 'answer':
      return {
        ...state,
        answer: action.data.answer ?? '',
        evidenceCount: action.data.evidence_count ?? state.evidenceCount,
      };
    case 'done':
      return {
        ...state,
        running: false,
        done: true,
        queryId: action.data.query_id || state.queryId,
        elapsedMs: action.data.elapsed_ms ?? state.elapsedMs,
      };
    case 'artifact_meta':
      return {
        ...state,
        models: action.models ?? state.models,
        nodeCounts: action.nodes ?? state.nodeCounts,
        elapsedMs: action.elapsedMs ?? state.elapsedMs,
      };
    case 'error':
      return {
        ...state,
        running: false,
        done: true,
        error: action.data,
      };
    case 'stopped':
      return { ...state, running: false, error: { message: 'Run stopped by user.' } };
    default:
      return state;
  }
}

function findNode(node, id) {
  if (!node) return null;
  if (node.id === id) return node;
  for (const child of node.children || []) {
    const hit = findNode(child, id);
    if (hit) return hit;
  }
  return null;
}

export function useQueryRun() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const abortRef = useRef(null);

  const run = useCallback(async (question, datasetId) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: 'run_start', question });
    try {
      const stream = streamQuery({ question, datasetId }, { signal: controller.signal });
      for await (const frame of stream) {
        dispatch({ type: frame.event, data: frame.data || {} });
        if (frame.event === 'done') {
          // Enrich the footer with models / node counts from result.json.
          const qid = frame.data?.query_id;
          if (qid) {
            getArtifact(qid, 'result.json', controller.signal)
              .then((result) => {
                dispatch({
                  type: 'artifact_meta',
                  models: result.models,
                  nodes: result.nodes,
                  elapsedMs: result.elapsed_ms,
                });
              })
              .catch(() => {});
          }
        }
      }
    } catch (err) {
      if (err?.name === 'AbortError') {
        dispatch({ type: 'stopped' });
      } else {
        dispatch({ type: 'error', data: { message: String(err?.message || err) } });
      }
    }
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: 'reset' });
  }, []);

  return { state, run, stop, reset };
}
