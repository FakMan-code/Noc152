"""CLI for the generic operational knowledge motor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from okm.ask import export_payload
from okm.pipeline import build_expediente, format_service_card
from okm.serve import run_server
from okm.store import ExpedienteStore
from okm.visual_state import board_text


def _workspace(args: argparse.Namespace) -> Path:
    return Path(args.workspace).expanduser().resolve()


def cmd_ingest(args: argparse.Namespace) -> int:
    ws = _workspace(args)
    store = build_expediente(
        args.source,
        ws,
        config_path=Path(args.config) if args.config else None,
    )
    run = store.latest_run() or {}
    services = store.list_services()
    print(f"Workspace: {ws}")
    print(f"Source:    {run.get('source_uri')}")
    print(f"Run:       {run.get('run_id')}")
    print(
        f"Files:     seen={run.get('files_seen')} ingested={run.get('files_ingested')} skipped={run.get('files_skipped')}"
    )
    print(f"Claims:    {run.get('claims_written')}  gaps={run.get('gaps_written')}")
    print(f"Services:  {', '.join(s.name for s in services) or '(none)'}")
    if run.get("errors_json") and run["errors_json"] != "[]":
        print(f"Errors:    {run['errors_json']}")
    store.close()
    return 0


def cmd_services(args: argparse.Namespace) -> int:
    store = ExpedienteStore(_workspace(args))
    for svc in store.list_services():
        print(f"{svc.name}\t{svc.service_id}\t{svc.root_path}")
    store.close()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = ExpedienteStore(_workspace(args))
    print(format_service_card(store, args.service))
    store.close()
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    store = ExpedienteStore(_workspace(args))
    text = store.open_excerpt(args.evidence_id)
    if text is None:
        print(f"Evidence not found: {args.evidence_id}", file=sys.stderr)
        store.close()
        return 1
    ev = store.get_evidence(args.evidence_id)
    assert ev is not None
    print(f"# {ev.openable_ref()}  sha={ev.blob_sha[:12]}")
    print(text)
    store.close()
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    store = ExpedienteStore(_workspace(args))
    svc = store.get_service(args.service)
    if not svc:
        print("Service not found", file=sys.stderr)
        store.close()
        return 1
    print(json.dumps(store.coverage_for(svc.service_id), indent=2))
    store.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export a service card as JSON (API/Action-shaped, still generic)."""
    store = ExpedienteStore(_workspace(args))
    svc = store.get_service(args.service)
    if not svc:
        print("Service not found", file=sys.stderr)
        store.close()
        return 1
    print(json.dumps(export_payload(store, svc), indent=2, ensure_ascii=False))
    store.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Open the local NOC briefing UI over a workspace."""
    run_server(_workspace(args), host=args.host, port=args.port)
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    """ASCII ops board from the NumPy state engine (no live metrics required)."""
    store = ExpedienteStore(_workspace(args))
    print(board_text(store, mode=args.mode))
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="okm",
        description="Noc152 — expediente operacional genérico desde cualquier repo",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--workspace",
        default=".okm_workspace",
        help=(
            "Expediente a abrir (default: .okm_workspace). "
            "En serve, también lista hermanos .demo_* como raíces independientes."
        ),
    )
    common.add_argument("--config", default=None, help="Optional TOML config path")

    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser(
        "ingest",
        parents=[common],
        help="Build expediente from a local path or public git URL",
    )
    ing.add_argument("source", help="Local path or git URL")
    ing.set_defaults(func=cmd_ingest)

    svc = sub.add_parser("services", parents=[common], help="List resolved services")
    svc.set_defaults(func=cmd_services)

    show = sub.add_parser("show", parents=[common], help="Show human-readable service card")
    show.add_argument("service", help="Service name, alias, or id")
    show.set_defaults(func=cmd_show)

    op = sub.add_parser("open", parents=[common], help="Re-open evidence excerpt by id")
    op.add_argument("evidence_id")
    op.set_defaults(func=cmd_open)

    cov = sub.add_parser("coverage", parents=[common], help="Coverage counts by facet")
    cov.add_argument("service")
    cov.set_defaults(func=cmd_coverage)

    exp = sub.add_parser("export", parents=[common], help="Export service expediente as JSON")
    exp.add_argument("service")
    exp.set_defaults(func=cmd_export)

    srv = sub.add_parser(
        "serve",
        parents=[common],
        help="Local briefing UI: facets + audited Q&A over the expediente",
    )
    srv.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    srv.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    srv.set_defaults(func=cmd_serve)

    board = sub.add_parser(
        "board",
        parents=[common],
        help="ASCII radar/heatmap/sparklines (NumPy; sin datos ops usa ?)",
    )
    board.add_argument(
        "--mode",
        choices=("operator", "showcase"),
        default="operator",
        help="operator: huecos explícitos. showcase: series simuladas.",
    )
    board.set_defaults(func=cmd_board)

    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
