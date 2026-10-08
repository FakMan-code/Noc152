# Código del nodo + auditoría (v0.2+)

## Por qué el asistente decía “no hay código de Combinado”

El nodo **Combinado** en el mapa propio es una **capa lógica**. El LLM solo veía el blurb del dossier, no `okm/noc_combined.py`.

## Camino actual (sin MCP)

1. Mapa `NODE_SOURCE_MAP` en `okm/node_sources.py`: nodo → archivos del repo.
2. Si preguntás por código (o tenés el nodo en foco), se **leen esos archivos del disco** (`source_uri` del ingest).
3. Respuesta modo `source`: **resumen corto** (primario + anexos). El chat no vuelca 20k chars.
4. UI: **Copiar** / **Descargar** archivo completo, o **.zip** de todos.
5. APIs: `GET /api/source/file?focus=&path=` · `GET /api/source/bundle?focus=`
6. Cada `/api/ask` escribe un evento JSONL en:

```text
<workspace>/audit/ask/YYYYMMDD.jsonl
```

Campos: pregunta, foco, modo, modelo, paths abiertos, preview de respuesta, `auth.kind=local`.

## ¿Cuándo MCP?

Cuando el código **no esté** en el workspace local (otro repo, otra máquina, credenciales).

| Fase | Qué |
|---|---|
| **Ahora** | Lectura local + audit JSONL |
| **Después** | Tool MCP `get_file` / `search` con el mismo audit (canal=`mcp`) |

MCP no reemplaza el expediente: es un **brazo** para ir a buscar; el log queda igual.

## Docs NOC (primario) vs contrato API

- **`/docs`** — ficha operativa generada desde Combinado (audiencia operador NOC).
- **`/docs/api`** — Scalar/OpenAPI (técnico; suele verse vacío si el JSON no trae descripciones).

Desde el Asistente: **Docs NOC**. El grafo 3D sigue siendo la cara principal.

## Probar

```powershell
python -m okm.cli serve --workspace .demo_noc152
# En la UI: seleccioná Combinado → “dame el código fuente de combinado”
# Logs: .demo_noc152/audit/ask/
# Docs: http://127.0.0.1:8765/docs?spec=noc152
```
