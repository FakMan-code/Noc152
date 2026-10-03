# Noc152

Expediente operacional + mapa 3D consultable.

Noc152 lee un repositorio (local o git público), detecta **servicios** por manifiestos, guarda claims con evidencia abríble y los muestra en un briefing interactivo. No asume productos ni organizaciones: la fuente la elegís vos.

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
cd c:\Users\mglembo\Desktop\Proyecto-Noc-152

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
| Click en nodo | Detalle |
| Doble click / Ampliar | Acercar (o entrar al servicio en vista sistema) |
| Traza | Animar caminos |
| Preguntar | Agente local grounded en el expediente |

## Colores de salud

| Color | Significado |
|---|---|
| Verde | Ok |
| Amarillo | Alerta a revisar (cuando haya fuente ops) |
| Rojo | Roto / fallando (reservado a evidencia ops) |
| Violeta | Hub del sistema (nodo principal del mapa) |

En modo solo-repo (sin monitoreo), los servicios se muestran en verde.

## Artefactos en `--workspace`

| Artefacto | Rol |
|---|---|
| `expediente.sqlite3` | servicios, claims, relations, evidence, runs |
| `blobs/` | contenido content-addressed (SHA-256) |
| `source_cache/` | clone shallow del git (si aplica) |

## API local (con `serve`)

- `GET /api/meta`  
- `GET /api/graph/__system__` — mapa de todos los servicios  
- `GET /api/graph/<servicio>` — expediente 3D de un servicio  
- `POST /api/ask` — `{ "question": "...", "service": "<nombre>" }`  
- `GET /api/evidence/<id>`  

## Comandos CLI

```text
python -m okm.cli ingest <path|git-url> [--workspace DIR] [--config FILE]
python -m okm.cli services [--workspace DIR]
python -m okm.cli show <service> [--workspace DIR]
python -m okm.cli open <evidence_id> [--workspace DIR]
python -m okm.cli coverage <service> [--workspace DIR]
python -m okm.cli export <service> [--workspace DIR]
python -m okm.cli serve [--workspace DIR] [--host 127.0.0.1] [--port 8765]
```

## Qué demuestra (y qué no)

**Sí**

- Ingesta genérica  
- Expediente tipado con procedencia  
- Mapa 3D + drill-down  
- Preguntas auditadas contra el expediente  

**Todavía no**

- Conectores ops (monitoreo/alertas) vía MCP  
- Autenticación / multi-usuario  
- Multi-fuente completa más allá del repo  

## Arquitectura en una frase

`ingest` → expediente SQLite → `layout3d` (NumPy) + UI Three.js → `ask`/`agent` (retrieval + Ollama opcional).

El grafo se inspira en la idea de diagramas explorables (tipo Archify: nodos, relaciones, detalle), pero el motor y los datos son propios de Noc152.
