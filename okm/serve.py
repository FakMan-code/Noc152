"""Local briefing server: HTML UI + JSON API over an expediente workspace."""

from __future__ import annotations

import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from okm import __version__
from okm.agent import agent_answer
from okm.ask import brief_for_ui, export_payload
from okm.archify_adapter import find_archify_spec
from okm.config import load_config
from okm.engines import GraphEngine, available_engines, build_graph, parse_engine
from okm.openapi_graph import (
    find_openapi_spec,
    list_openapi_specs,
    load_openapi_spec,
    resolve_openapi_spec,
)
from okm.humanize import is_noise_service, product_name
from okm.node_sources import build_source_zip, read_single_source
from okm.noc_docs import build_noc_handbook, render_noc_handbook_markdown
from okm.store import ExpedienteStore

STATIC_DIR = Path(__file__).resolve().parent / "static"


class BriefingApp:
    def __init__(self, workspace: Path, host: str = "127.0.0.1", port: int = 8765):
        self.workspace = workspace.expanduser().resolve()
        self.host = host
        self.port = port

    def open_store(self) -> ExpedienteStore:
        return ExpedienteStore(self.workspace)

    def meta(self) -> dict[str, Any]:
        store = self.open_store()
        try:
            run = store.latest_run() or {}
            services = store.list_services()
            ui = load_config().get("ui", {}) or {}
            scopes = ui.get("scopes") or [{"id": "pais", "label": "País", "options": []}]
            return {
                "product_name": product_name(),
                "version": __version__,
                "default_engine": GraphEngine.COMBINED.value,
                "workspace": str(self.workspace),
                "source_uri": run.get("source_uri"),
                "run_id": run.get("run_id"),
                "files_ingested": run.get("files_ingested"),
                "claims_written": run.get("claims_written"),
                "gaps_written": run.get("gaps_written"),
                "scopes": scopes,
                "services": [
                    {
                        "id": s.service_id,
                        "name": s.name,
                        "summary": s.summary,
                        "root_path": s.root_path,
                    }
                    for s in services
                    if not is_noise_service(s.name)
                ],
                "has_system_view": sum(1 for s in services if not is_noise_service(s.name)) >= 1,
                "archify_spec": (
                    str(find_archify_spec(self.workspace).relative_to(self.workspace))
                    if find_archify_spec(self.workspace)
                    else None
                ),
                "openapi_spec": _rel_or_abs(find_openapi_spec(self.workspace), self.workspace),
                "openapi_specs": list_openapi_specs(self.workspace),
                "docs_url": "/docs",
                "docs_api_url": "/docs/api",
                "engines": available_engines(self.workspace),
            }
        finally:
            store.close()


def _rel_or_abs(path: Path | None, workspace: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _json_bytes(payload: Any, status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def make_handler(app: BriefingApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[okm-brief] {self.address_string()} {fmt % args}")

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
            *,
            download_name: str | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            if download_name:
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{download_name}"',
                )
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._handle_get()
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                status, body, ctype = _json_bytes({"ok": False, "error": str(exc)}, 500)
                self._send(status, body, ctype)

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._handle_post()
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                status, body, ctype = _json_bytes({"ok": False, "error": str(exc)}, 500)
                self._send(status, body, ctype)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _handle_get(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            qs = parse_qs(parsed.query)

            if path in {"/", "/index.html"}:
                html = (STATIC_DIR / "index.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
                return

            # Docs NOC (audiencia operador) — primaria
            if path in {"/docs", "/docs/", "/docs/noc", "/docs/noc/"}:
                html = (STATIC_DIR / "noc-docs.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
                return

            # Contrato OpenAPI / Scalar — secundario (técnico; a menudo incompleto)
            if path in {"/docs/api", "/docs/api/", "/swagger", "/swagger/", "/scalar", "/scalar/"}:
                html = (STATIC_DIR / "docs.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
                return

            if path in {"/api/docs/noc", "/api/docs/noc.json"}:
                store = app.open_store()
                try:
                    payload = build_noc_handbook(store, workspace=app.workspace)
                finally:
                    store.close()
                status, body, ctype = _json_bytes(payload)
                self._send(status, body, ctype)
                return

            if path == "/api/docs/noc.md":
                store = app.open_store()
                try:
                    hand = build_noc_handbook(store, workspace=app.workspace)
                    md = render_noc_handbook_markdown(hand).encode("utf-8")
                finally:
                    store.close()
                self._send(
                    200,
                    md,
                    "text/markdown; charset=utf-8",
                    download_name="noc-handbook.md",
                )
                return

            if path == "/api/openapi":
                specs = list_openapi_specs(app.workspace)
                # Don't leak absolute paths to the browser
                public = [
                    {k: v for k, v in s.items() if k != "path"} for s in specs
                ]
                status, body, ctype = _json_bytes({"specs": public})
                self._send(status, body, ctype)
                return

            if path.startswith("/api/openapi/"):
                sid = path[len("/api/openapi/") :].strip("/")
                if not sid:
                    status, body, ctype = _json_bytes({"ok": False, "error": "missing spec"}, 400)
                    self._send(status, body, ctype)
                    return
                spec_path = resolve_openapi_spec(sid, app.workspace)
                if spec_path is None:
                    status, body, ctype = _json_bytes({"ok": False, "error": "not found"}, 404)
                    self._send(status, body, ctype)
                    return
                try:
                    payload = load_openapi_spec(spec_path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    status, body, ctype = _json_bytes({"ok": False, "error": str(exc)}, 500)
                    self._send(status, body, ctype)
                    return
                status, body, ctype = _json_bytes(payload)
                self._send(status, body, ctype)
                return

            if path.startswith("/static/"):
                rel = path[len("/static/") :]
                target = (STATIC_DIR / rel).resolve()
                if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                    return
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                self._send(200, target.read_bytes(), ctype)
                return

            if path == "/api/meta":
                status, body, ctype = _json_bytes(app.meta())
                self._send(status, body, ctype)
                return

            if path == "/api/services":
                store = app.open_store()
                try:
                    payload = [
                        {
                            "id": s.service_id,
                            "name": s.name,
                            "summary": s.summary,
                            "root_path": s.root_path,
                            "aliases": s.aliases,
                        }
                        for s in store.list_services()
                    ]
                finally:
                    store.close()
                status, body, ctype = _json_bytes({"services": payload})
                self._send(status, body, ctype)
                return

            if path.startswith("/api/services/"):
                name = path[len("/api/services/") :].strip("/")
                if not name:
                    status, body, ctype = _json_bytes({"ok": False, "error": "missing service"}, 400)
                    self._send(status, body, ctype)
                    return
                mode = (qs.get("view") or ["brief"])[0]
                store = app.open_store()
                try:
                    svc = store.get_service(name)
                    if not svc:
                        status, body, ctype = _json_bytes({"ok": False, "error": "not found"}, 404)
                        self._send(status, body, ctype)
                        return
                    payload = export_payload(store, svc) if mode == "export" else brief_for_ui(store, svc)
                finally:
                    store.close()
                status, body, ctype = _json_bytes(payload)
                self._send(status, body, ctype)
                return

            if path.startswith("/api/evidence/"):
                eid = path[len("/api/evidence/") :].strip("/")
                store = app.open_store()
                try:
                    ev = store.get_evidence(eid)
                    if not ev:
                        status, body, ctype = _json_bytes({"ok": False, "error": "not found"}, 404)
                        self._send(status, body, ctype)
                        return
                    excerpt = store.open_excerpt(eid) or ev.excerpt
                    payload = {
                        "id": ev.evidence_id,
                        "path": ev.path,
                        "ref": ev.openable_ref(),
                        "locator": ev.locator.to_json(),
                        "excerpt": excerpt,
                        "blob_sha": ev.blob_sha,
                    }
                finally:
                    store.close()
                status, body, ctype = _json_bytes(payload)
                self._send(status, body, ctype)
                return

            if path == "/api/source/file":
                focus = (qs.get("focus") or [None])[0]
                rel = (qs.get("path") or [None])[0]
                if not rel:
                    status, body, ctype = _json_bytes({"ok": False, "error": "missing path"}, 400)
                    self._send(status, body, ctype)
                    return
                store = app.open_store()
                try:
                    file_hit = read_single_source(
                        store, focus_node=str(focus) if focus else None, rel_path=str(rel)
                    )
                finally:
                    store.close()
                if not file_hit:
                    status, body, ctype = _json_bytes({"ok": False, "error": "not found"}, 404)
                    self._send(status, body, ctype)
                    return
                raw = file_hit["content"].encode("utf-8")
                name = Path(file_hit["path"]).name
                ctype = "text/plain; charset=utf-8"
                if name.endswith(".py"):
                    ctype = "text/x-python; charset=utf-8"
                elif name.endswith(".html"):
                    ctype = "text/html; charset=utf-8"
                self._send(200, raw, ctype, download_name=name)
                return

            if path == "/api/source/bundle":
                focus = (qs.get("focus") or [None])[0]
                store = app.open_store()
                try:
                    packed = build_source_zip(
                        store, focus_node=str(focus) if focus else None
                    )
                finally:
                    store.close()
                if not packed:
                    status, body, ctype = _json_bytes({"ok": False, "error": "not found"}, 404)
                    self._send(status, body, ctype)
                    return
                raw, zip_name = packed
                self._send(200, raw, "application/zip", download_name=zip_name)
                return

            if path.startswith("/api/graph/"):
                name = path[len("/api/graph/") :].strip("/")
                if not name:
                    status, body, ctype = _json_bytes({"ok": False, "error": "missing service"}, 400)
                    self._send(status, body, ctype)
                    return
                engine = parse_engine((qs.get("engine") or [GraphEngine.COMBINED.value])[0])
                store = app.open_store()
                try:
                    # Archify IR / OpenAPI: service-agnostic full graph.
                    if engine == GraphEngine.OPENAPI or (
                        find_archify_spec(app.workspace) and engine == GraphEngine.ARCHIFY
                    ):
                        payload = build_graph(
                            store,
                            service=None,
                            engine=engine,
                            system=True,
                            workspace=app.workspace,
                        )
                    elif name in {"__system__", "system", "_system", "__archify__", "__openapi__"}:
                        payload = build_graph(
                            store,
                            service=None,
                            engine=engine,
                            system=True,
                            workspace=app.workspace,
                        )
                    else:
                        svc = store.get_service(name)
                        if not svc:
                            status, body, ctype = _json_bytes({"ok": False, "error": "not found"}, 404)
                            self._send(status, body, ctype)
                            return
                        payload = build_graph(
                            store,
                            service=svc,
                            engine=engine,
                            system=False,
                            workspace=app.workspace,
                        )
                finally:
                    store.close()
                status, body, ctype = _json_bytes(payload)
                self._send(status, body, ctype)
                return

            self._send(404, b'{"ok":false,"error":"not found"}', "application/json; charset=utf-8")

        def _handle_post(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path != "/api/ask":
                self._send(404, b'{"ok":false,"error":"not found"}', "application/json; charset=utf-8")
                return
            data = self._read_json()
            question = str(data.get("question") or "")
            service = data.get("service")
            focus_node = data.get("focus_node") or data.get("node") or data.get("selected")
            use_llm = data.get("use_llm", True)
            store = app.open_store()
            try:
                payload = agent_answer(
                    store,
                    question,
                    service_name=str(service) if service else None,
                    focus_node=str(focus_node) if focus_node else None,
                    use_llm=bool(use_llm),
                )
            finally:
                store.close()
            status, body, ctype = _json_bytes(payload)
            self._send(status, body, ctype)

    return Handler


def run_server(workspace: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    app = BriefingApp(workspace, host=host, port=port)
    if not (STATIC_DIR / "index.html").is_file():
        raise FileNotFoundError(f"Missing UI: {STATIC_DIR / 'index.html'}")
    handler = make_handler(app)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print("Noc152", flush=True)
    print(f"  workspace: {app.workspace}", flush=True)
    print(f"  open:      {url}", flush=True)
    print("  Ctrl+C to stop", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        httpd.server_close()
