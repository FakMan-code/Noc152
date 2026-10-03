# Operational Knowledge Motor (OKM)

Motor genérico que lee un repositorio (local o git público), construye un **expediente operacional** consultable y separa:

- **observed** — hecho con evidencia abríble  
- **inferred** — hipótesis / heurística débil  
- **gap** — lo que no se encontró o está fuera de alcance  

No hardcodea productos, servicios ni organizaciones. Prex u otro sistema se conectan después como *fuente*, no como lógica del motor.

## Demo rápida (repo público)

Requiere Python 3.11+ y `git` en el PATH.

```powershell
cd c:\Users\mglembo\Desktop\Proyecto-Noc-152

# 1) Ingestar un repo público (ejemplo: Flask)
python -m okm.cli ingest https://github.com/pallets/flask --workspace .demo_flask

# 2) Listar servicios detectados
python -m okm.cli services --workspace .demo_flask

# 3) Ver la ficha (reemplazá el nombre si el listado muestra otro)
python -m okm.cli show flask --workspace .demo_flask

# 4) Export JSON (forma consumible por una Action / API)
python -m okm.cli export flask --workspace .demo_flask > flask_expediente.json
```

Otro ejemplo más chico:

```powershell
python -m okm.cli ingest https://github.com/encode/httpx --workspace .demo_httpx
python -m okm.cli services --workspace .demo_httpx
python -m okm.cli show httpx --workspace .demo_httpx
```

## Qué queda guardado

En `--workspace`:

| Artefacto | Rol |
|---|---|
| `expediente.sqlite3` | servicios, claims, relations, evidence, runs |
| `blobs/` | contenido content-addressed (SHA-256) |
| `source_cache/` | clone shallow del git (si aplica) |

Cada claim **observed** apunta a evidencia con `path` + líneas.  
`okm open <evidence_id>` reabre el fragmento desde el blob.

## Principios en el código

1. Unidad = **servicio** (heurística por manifiestos: `package.json`, `pyproject.toml`, `go.mod`, `Dockerfile`, …).  
2. Sin evidencia no se acepta `observed` (se degrada a `inferred`).  
3. Facetas sin señales del repo → `gap` explícito (`signals`, `failure` en demo repo-only).  
4. Reglas de la organización en `config/default.toml`, no nombres de negocio en el código.

## Comandos

```text
python -m okm.cli ingest <path|git-url> [--workspace DIR] [--config FILE]
python -m okm.cli services [--workspace DIR]
python -m okm.cli show <service> [--workspace DIR]
python -m okm.cli open <evidence_id> [--workspace DIR]
python -m okm.cli coverage <service> [--workspace DIR]
python -m okm.cli export <service> [--workspace DIR]
```

## Qué es esta demo (y qué no)

**Sí demuestra**

- Ingesta genérica  
- Expediente tipado consultable  
- Procedencia abríble  
- Observado / inferido / hueco  
- Export listo para enganchar a Copilot Studio después  

**No es todavía**

- Datadog / alertas  
- Multi-fuente Prex completa  
- LLM en el pipeline (el briefing usa retrieval determinista)  

## Noc152 (mapa 3D + preguntas auditadas)

Viewer estilo Archify (nodos / edges / drill-down) con estética Cursor. El layout 3D lo calcula **NumPy**; el navegador usa Three.js (órbita, zoom con rueda, click para detalle).

```powershell
pip install -r requirements.txt

# Demo microservicios (recomendado): Online Boutique de Google
python -m okm.cli ingest https://github.com/GoogleCloudPlatform/microservices-demo --workspace .demo_boutique
python -m okm.cli serve --workspace .demo_boutique

# Demo chica (librería, un solo "servicio"):
# python -m okm.cli serve --workspace .demo_httpx
# → http://127.0.0.1:8765/
```

- Click izquierdo = orbitar · rueda = zoom · **click-rueda (MMB)** = panear el mapa  
- Click = panel · doble click / **Ampliar** = acercar · **Traza** / filtros por área  
- Preguntas: agente local via **Ollama `qwen2.5:7b`** + dossier del expediente (si Ollama falla, usa retrieval)  

Endpoints:

- `GET /api/meta` — workspace / run / servicios  
- `GET /api/graph/<nombre>` — escena 3D (nodos, edges, details)  
- `GET /api/services/<nombre>` — brief por faceta  
- `POST /api/ask` — `{ "question": "...", "service": "httpx" }`  
- `GET /api/evidence/<id>` — excerpt abríble  

## Siguiente paso natural

1. Publicar `export` / `ask` como Action OpenAPI para Copilot Studio (contrato HTTP del briefing).  
2. Segunda fuente (docs) con el mismo contrato.  
3. Resolver servicio desde una alerta sin hardcodear nombres.
