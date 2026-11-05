"""Command line entry points: index, query, serve."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jevrag",
        description="GeoAgenticRag — JEV-driven Geographic Tree-RAG",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build a dataset index from CSV/GeoJSON files")
    p_index.add_argument("paths", nargs="+", type=Path, help="input data files")
    p_index.add_argument("--out", type=Path, default=Path(".runtime/data"),
                         help="output directory")
    p_index.add_argument("--id", default="demo", help="dataset id")

    p_query = sub.add_parser("query", help="run one question without a server")
    p_query.add_argument("question")
    p_query.add_argument("--dataset", default=None)
    p_query.add_argument("--config", type=Path, default=None,
                         help="datasets.json produced by `jevrag index` "
                              "(default: .runtime/data/datasets.json)")

    p_serve = sub.add_parser("serve", help="start the HTTP API + frontend")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)

    if args.command == "index":
        from .dataset import build_dataset
        result = build_dataset(args.paths, args.out, args.id)
        print(json.dumps(result, indent=2))
        # Write/refresh a datasets.json pointing at the new build.
        datasets_file = args.out / "datasets.json"
        entry = {"db": result["db"], "index": result["index"]}
        spec = {"default": args.id, "datasets": {args.id: entry}}
        datasets_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        print(f"wrote {datasets_file}", file=sys.stderr)
        return 0

    from .config import Settings

    settings = Settings.load()
    if args.command == "serve":
        import uvicorn

        if args.host:
            settings.host = args.host
        if args.port:
            settings.port = args.port
        from .server import create_app
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                    log_level="info")
        return 0

    # query
    if args.config is not None:
        settings.datasets_file = args.config
    from .server import Catalog, build_orchestrator
    catalog = Catalog(settings)
    dataset = catalog.get(args.dataset)
    orch = build_orchestrator(settings, dataset)
    events: list[str] = []

    def sink(event: str, data: dict) -> None:
        events.append(event)
        if event in {"node_start", "jev_decision", "answer", "error"}:
            print(f"[{event}] {json.dumps(data, ensure_ascii=False)[:200]}",
                  file=sys.stderr)

    result = orch.run(args.question, sink)
    print(json.dumps({k: result[k] for k in
                      ("answer", "nodes", "evidence_count", "elapsed_ms", "models")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
