import { readSse } from './sse.js';

async function jsonFetch(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail?.message || body?.detail || body?.error || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

/** GET /health -> {schema_version, status, mock, datasets} */
export function getHealth(signal) {
  return jsonFetch('/health', { signal });
}

/** GET /api/v1/datasets -> {default, datasets: [ids]} */
export function getDatasets(signal) {
  return jsonFetch('/api/v1/datasets', { signal });
}

/** GET /api/v1/history?limit= -> {queries: [{query_id, question, answer, ...}]} */
export function getHistory(limit = 50, signal) {
  return jsonFetch(`/api/v1/history?limit=${encodeURIComponent(limit)}`, { signal });
}

/** GET /api/v1/queries/{id}/artifacts/{name} */
export function getArtifact(queryId, name, signal) {
  return jsonFetch(
    `/api/v1/queries/${encodeURIComponent(queryId)}/artifacts/${encodeURIComponent(name)}`,
    { signal },
  );
}

/**
 * POST /api/v1/query/stream -> yields {event, data} SSE frames.
 * Aborting `signal` cancels the underlying stream.
 */
export async function* streamQuery({ question, datasetId }, { signal } = {}) {
  const body = { question };
  if (datasetId) body.dataset_id = datasetId;
  const res = await fetch('/api/v1/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const parsed = await res.json();
      detail = parsed?.detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
  }
  yield* readSse(res);
}
