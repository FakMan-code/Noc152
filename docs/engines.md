# Motores del mapa 3D (Noc152 v0.2)

El selector del topbar cambia **qué grafo** se proyecta. Misma UI; distinta fuente de verdad.

## Combinado NOC (default desde v0.2)

**Para qué:** entender la app en 30 segundos — roles humanos + quién depende de quién.

| Qué muestra | Cómo |
|---|---|
| Nodos | Producto + servicios con roles (`Login`, `Cuentas`, `Puerta API`…) |
| Formas | Por rol (pantalla, hex API, esfera core, etc.) |
| Aristas | Deps entre servicios (1 punta / 2 puntas ida-vuelta) |
| Colores | Neutro / violeta hub; verde·amarillo·rojo **solo** con ops real |
| Drill | Entrás a un servicio → vecinos + foco |

No mete endpoints ni “vigilar”. Eso vive en OpenAPI.

Código: `okm/noc_combined.py`.

## Archify

**Para qué:** diagrama de arquitectura curado (IR Archify JSON).

Nodos = componentes del IR (Client, módulos, boundaries). Bueno si ya tenés un `architecture.json` generado/validado con Archify. No es el expediente de claims/gaps.

## Noc152 (expediente)

**Para qué:** profundidad operativa del scan: facetas, claims, evidencia, gaps.

Más denso y “técnico”. Útil cuando querés abrir evidencia o ver cobertura del scan, no para la historia de producto.

## OpenAPI

**Para qué:** contrato HTTP — tags → operations → schemas.

Es el **borde** (cómo se llama la API), no el cerebro del NOC. Complementa Combinado; no lo reemplaza.

---

## Vs el proyecto anterior (knowledge-engine / chunking)

| | Proyecto anterior | Noc152 Combinado |
|---|---|---|
| Carga | Chunking pesado del código → lento | Ingest → SQLite; el mapa sale del expediente ya indexado |
| Preguntas | RAG sobre trozos; respuestas genéricas | Dossier del mapa/expediente + Ollama opcional (grounded) |
| Vista | Documental / L1 | Historia de producto + deps (Combinado) |
| Semáforo | Mezclado o ausente | RYG solo nodos con señal ops |

La idea: **primero el mapa que se entiende**, después profundidad (Noc152/OpenAPI/ops). El chunking masivo no es el camino de arranque.
