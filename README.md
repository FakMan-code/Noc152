# Noc152

**v0.2.1** · Repo: https://github.com/FakMan-code/Noc152

Expediente operacional + mapa 3D consultable.

Noc152 lee un repositorio (local o git público), detecta **servicios** por manifiestos, guarda claims con evidencia abríble y los muestra en un briefing interactivo. No asume productos ni organizaciones: la fuente la elegís vos.

**Arranque del mapa:** motor **Combinado NOC** (roles humanos + deps). Detalle de motores: [`docs/engines.md`](docs/engines.md).

## Principios

1. Unidad = **servicio** (heurística por `package.json`, `pyproject.toml`, `go.mod`, `Dockerfile`, …).  
2. Sin evidencia no hay `observed` (queda `inferred` o `gap`).  
3. Reglas locales en `config/default.toml`, no nombres de negocio en el código.  
4. Preguntas: dossier del expediente + LLM local opcional (Ollama); si no hay modelo, retrieval determinista.

## Requisitos

- Python 3.11+  
- `git` en el PATH (para URLs)  
- Opcional: [Ollama](https://ollama.com) con un modelo de chat (p. ej. `qwen2.5:7b`) para respuestas tipo agente  

```powershell
pip install -r requirements.txt
```

## Uso rápido

```powershell
cd <ruta-de-Noc152>

# Ingestar cualquier repo (ejemplo público de microservicios)
python -m okm.cli ingest https://github.com/GoogleCloudPlatform/microservices-demo --workspace .demo_ws

# Listar / inspeccionar
python -m okm.cli services --workspace .demo_ws
python -m okm.cli show <servicio> --workspace .demo_ws

# Briefing 3D + preguntas
python -m okm.cli serve --workspace .demo_ws
# → http://127.0.0.1:8765/
```

También podés apuntar a una carpeta local:

```powershell
python -m okm.cli ingest . --workspace .demo_self
python -m okm.cli serve --workspace .demo_self
```

## Controles del mapa

| Acción | Efecto |
|---|---|
| Click izquierdo + arrastrar | Orbitar |
| Rueda | Zoom |
| Click-rueda + arrastrar | Panear |
| Click en nodo | Entrar a la siguiente capa (hijos, o expediente del servicio) |
| Entrar / Ampliar | Entrar a la capa, o acercar si ya es la última |
| Atrás (Alt+←) | Capa anterior |
| Preguntar | Agente local grounded en el expediente |

## Colores de salud

| Color | Significado |
|---|---|
| Gris | Sin señal ops (default del mapa) |
| Verde | Ok confirmado por ops (semáforo) |
| Amarillo | Alerta a revisar (semáforo) |
| Rojo | Problema / falla (semáforo) |
| Violeta | Hub del sistema (nodo principal) |

Aristas: cyan + 1 punta = un sentido; lavanda + 2 puntas = ida/vuelta. Semáforo = solo nodos.

## Artefactos en `--workspace`

| Artefacto | Rol |
|---|---|
| `expediente.sqlite3` | servicios, claims, relations, evidence, runs |
| `blobs/` | contenido content-addressed (SHA-256) |
| `source_cache/` | clone shallow del git (si aplica) |

## API local (con `serve`)

- `GET /api/meta`  
- `GET /api/graph/__system__` — mapa completo (todos los servicios)  
- `GET /api/graph/<servicio>` — expediente 3D de un servicio  
- `POST /api/ask` — `{ "question": "...", "service": "<nombre>" }`  
- `GET /api/evidence/<id>`  
- `GET /docs` — Scalar (referencia OpenAPI en lectura; el mapa 3D sigue siendo la vista principal)  
- `GET /api/openapi` — lista de specs · `GET /api/openapi/<id>` — JSON  


## Comandos CLI

```text
python -m okm.cli ingest <path|git-url> [--workspace DIR] [--config FILE]
python -m okm.cli services [--workspace DIR]
python -m okm.cli show <service> [--workspace DIR]
python -m okm.cli open <evidence_id> [--workspace DIR]
python -m okm.cli coverage <service> [--workspace DIR]
python -m okm.cli export <service> [--workspace DIR]
python -m okm.cli serve [--workspace DIR] [--host 127.0.0.1] [--port 8765]
python -m okm.cli board [--workspace DIR] [--mode operator|showcase]
```

## Qué demuestra (y qué no)

**Sí**

- Ingesta genérica  
- Expediente tipado con procedencia  
- Mapa 3D + drill-down por capas  
- Preguntas auditadas contra el expediente  

**Todavía no**

- Conectores ops (monitoreo/alertas) vía MCP  
- Autenticación / multi-usuario  
- Multi-fuente completa más allá del repo  

## Motores del mapa

| Motor | Qué ves |
|---|---|
| **Combinado NOC** (default) | Historia de la app: roles + formas + deps |
| Archify | IR de arquitectura curado |
| Noc152 | Facetas / claims / gaps del expediente |
| OpenAPI | Paths, ops y schemas (si hay spec) |

## Arquitectura en una frase

`ingest` → expediente SQLite → proyección 3D (Combinado / Archify / Noc152 / OpenAPI) → `ask`/`agent` (dossier + Ollama opcional).

El grafo se inspira en diagramas explorables, pero el cerebro y los datos son de Noc152 — no un segundo pipeline de chunking masivo.
