# JEV — the branch controller

**JEV** is the decision component at the heart of GeoAgenticRag. After every
branch of the query tree returns a result, JEV reads that result together with
the routes the planner declared on the node, and emits **one** decision. The
tree only ever changes through `QueryTree.apply`, which validates the decision
against the declared contract first.

## Decision contract

Input (`build_payload` in `jevrag/jev.py`):

```json
{
  "question": "Which parks are in the West End?",
  "branch": {
    "id": "n1",
    "query": "find parks in the West End",
    "tool": "sql",
    "routes": [{"id": "r_ok", "when": "success"}, {"id": "r_empty", "when": "empty"}]
  },
  "result": {
    "status": "success",
    "summary": "2 rows from SQL",
    "error": "",
    "row_count": 2,
    "evidence_ids": ["e1", "e2"]
  }
}
```

Output (validated by `validate_decision`):

```json
{
  "action": "complete" | "add_child" | "prune" | "fail",
  "route_id": "r_ok",
  "reason": "<= 80 chars",
  "follow_up": {"query": "...", "tool": "sql|search|none"}   // iff add_child
}
```

## What each action does

| action | effect |
|---|---|
| `complete` | node done; `always` children + children of `route_id` stay pending and become runnable; other conditional children are **pruned** |
| `add_child` | same as complete, plus one new child node (validated: tool known, query non-empty, node budget respected) |
| `prune` | node done; all conditional children pruned (even on the selected route); `always` children still run |
| `fail` | branch is unusable → the whole run fails. There is no fallback provider and no partial answer. |

## Guarantees

- `route_id` must be one of the node's declared routes — never invented.
- Route `when` values are `success` / `empty` / `error`, matched against the
  tool result status.
- JEV proposes; only `QueryTree.apply` commits. A rejected proposal becomes a
  run error, never a silently ignored mutation.
- Evidence recorded before a decision is **never dropped**, even for pruned
  branches — the plan changes, the observations don't.

## Serving JEV

Any OpenAI-compatible chat endpoint works (temperature 0, JSON reply). A
convenient deployment is a small dedicated model served by vLLM:

```bash
vllm serve <model> --served-model-name jev --port 8100 \
  --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}'
```

```bash
JEVRAG_JEV_URL=http://127.0.0.1:8100/v1 JEVRAG_JEV_MODEL=jev jevrag query "..."
```

`JEVRAG_MOCK=1` replaces JEV with a deterministic stand-in for tests and
offline demos.
