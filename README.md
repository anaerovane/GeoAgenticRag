# GeoAgenticRag

**JEV-driven Geographic Tree-RAG** — adaptive spatial question answering over an inspectable query tree.

A question becomes a **query tree** of small tasks. Each task runs one tool
(SQL / keyword search / reasoning) and returns a result. **JEV**, the branch
controller, then decides what happens next: finish the branch, spawn a
follow-up task, prune the remaining branches, or fail the run. Every
observation is kept in an **evidence tree** — even when its branch is later
pruned — and the final answer cites only that evidence.

```
question ──► planner ──► query tree
                            │  branch result
                            ▼
                     ┌────────────┐   decision   ┌────────────────┐
                     │    JEV     │─────────────►│ QueryTree.apply │
                     └────────────┘              └────────────────┘
                            │  evidence
                            ▼
                     evidence tree ──► answer [e1] [e2] …
```

## Highlights

- **JEV is the centerpiece.** One small model (or any OpenAI-compatible
  endpoint) receives the branch result plus the declared routes and emits one
  constrained JSON decision — `complete | add_child | prune | fail` + a route
  id. See [docs/jev.md](docs/jev.md).
- **Concise prompts.** All four prompts (planner / JEV / SQL / answer) live in
  [`jevrag/prompts.py`](jevrag/prompts.py) — a few hundred characters each,
  no mode-specific variants. Structure is enforced in code, not prose.
- **Validated mutations.** Only `QueryTree.apply` writes tree state; it
  rejects unknown routes, unknown actions and out-of-budget nodes.
- **Evidence survives pruning.** Observations are immutable once recorded.
- **No silent fallback.** A failed branch fails the run (`fail` → error
  propagates). Read-only SQL is enforced by a SQLite authorizer.
- **Offline mode.** `JEVRAG_MOCK=1` runs the whole pipeline with a
  deterministic stand-in — no GPU, no network.

## Quick start

```bash
pip install -e .

# 1. Build a dataset index from CSV/GeoJSON
jevrag index examples/city_poi.csv --out .runtime/data --id demo

# 2a. Ask a question offline (mock models)
JEVRAG_MOCK=1 jevrag query "Which parks are in the West End?"

# 2b. Ask against real models (OpenAI-compatible endpoints)
JEVRAG_PLANNER_URL=http://127.0.0.1:8000/v1 \
JEVRAG_JEV_URL=http://127.0.0.1:8100/v1 \
jevrag query "Which parks are in the West End?"

# 3. Serve the API (and the frontend if built)
jevrag serve --port 8080
curl -X POST http://127.0.0.1:8080/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which parks are in the West End?"}'
```

## HTTP API

| Route | Purpose |
|---|---|
| `GET /health` | readiness + dataset list |
| `GET /api/v1/datasets` | registered dataset ids |
| `POST /api/v1/query` | run one question, return full result |
| `POST /api/v1/query/stream` | same, as server-sent events |
| `GET /api/v1/queries/{id}/artifacts/{name}` | `request / events / query_tree / evidence / result / status` |
| `GET /api/v1/history` | recent queries |

SSE events: `query_started`, `tree`, `node_start`, `node_result`,
`jev_decision`, `evidence`, `answer`, `done`, `error`.

## Frontend

`frontend/` is a React + Vite app (query composer, live query tree, JEV
decision timeline, evidence panel):

```bash
cd frontend && npm install && npm run build   # served at /
```

## Layout

```
jevrag/
  prompts.py     all prompts (planner, JEV, SQL, answer)
  jev.py         JEV decision contract + client
  tree.py        query tree model; single write gate (QueryTree.apply)
  planner.py     question -> validated tree (with one repair retry)
  retrieval.py   BM25 source index (+ optional cross-encoder rerank)
  tools.py       sql / search / none; read-only SQLite + haversine()
  evidence.py    evidence tree + answer synthesis
  orchestrator.py the run loop
  dataset.py     CSV/GeoJSON -> sqlite + profiles + index
  server.py      FastAPI app
  cli.py         jevrag index | query | serve
```

## Configuration

| Env | Default | Meaning |
|---|---|---|
| `JEVRAG_MOCK` | off | deterministic offline models |
| `JEVRAG_PLANNER_URL` / `_MODEL` / `_KEY` | `:8000/v1` / `planner` / `local` | planner LLM |
| `JEVRAG_JEV_URL` / `_MODEL` / `_KEY` | `:8100/v1` / `jev` / `local` | JEV endpoint |
| `JEVRAG_ANSWER_URL` / `_MODEL` | planner's | answer LLM |
| `JEVRAG_RERANK_URL` | — | optional rerank endpoint |
| `JEVRAG_DATASETS` | `.runtime/data/datasets.json` | dataset registry |
| `JEVRAG_ARTIFACTS` | `.runtime/artifacts` | per-query artifacts |

## License

MIT — see [LICENSE](LICENSE).
