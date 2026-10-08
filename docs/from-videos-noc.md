# Qué tomar de los videos (Scalar / docs) vs el NOC Prex

## Video Scalar ([mSwn_gy9jPM](https://www.youtube.com/watch?v=mSwn_gy9jPM))

| Idea del video | Para Noc152 / NOC |
|---|---|
| OpenAPI JSON = contrato | Ya lo tenemos; el grafo OpenAPI + `/docs` lo leen |
| Scalar > Swagger (más claro) | Adoptado en `/docs` |
| Probar endpoints en la UI | **No es el foco NOC** — ocultamos Try it out / client |
| Dark mode, navegación por tags | Útil para operadores y para el agente |

Conclusión: Scalar como **referencia legible**, no como Postman embebido.

## Video docs / agentes (planes, changelog, context files)

| Idea | Encaje NOC |
|---|---|
| Docs según audiencia | Operador NOC ≠ desarrollador API |
| Context corto para agentes | `AGENTS.md` / dossier, no novelas |
| Planes en markdown | Alineado a Confluence + Jira del org |
| Changelog | Incidentes / releases operativos |

## Atlassian Prex (qué busca el NOC)

Fuentes: [NOC](https://prex-colab.atlassian.net/wiki/spaces/infrastructure/pages/38469714/NOC),
[Plan Estratégico NOC 2026](https://prex-colab.atlassian.net/wiki/spaces/infrastructure/pages/780664833/Plan+Estrat+gico+NOC+2026),
[NOC-Assistant ejecutivo](https://prex-colab.atlassian.net/wiki/spaces/infrastructure/pages/1223819281/Ejecutivo+NOC-Assistant+como+Asistente+Operativo),
[Proyecto IA-NOC](https://prex-colab.atlassian.net/wiki/spaces/infrastructure/pages/584548367/Proyecto+IA-NOC),
[Conocimiento operacional vivo](https://prex-colab.atlassian.net/wiki/spaces/infrastructure/pages/1562804326/Propuesta+tipo+diagramas+-+Plataforma+de+Conocimiento+Operacional+Vivo+para+el+NOC).

Prioridades org:
1. **Monitoreo + alertas + incidentes** (Datadog, severidad, escalamiento, postmortem).
2. **Catálogo / servicios críticos por país** y tablero 360°.
3. **Agente IA (Copilot Studio)** grounded en KB operativa (Confluence/SharePoint), no en “probar APIs”.
4. **Conocimiento vivo**: relaciones + evidencia + MCP/APIs cuando aporte.

## Qué priorizar en Noc152

1. **Grafo 3D Combinado** — historia y deps (cara NOC).
2. **Expediente + audit + código exportable** — evidencia para el agente.
3. **Scalar `/docs`** — contrato HTTP en lectura (cerebro / agentes).
4. **No** construir un laboratorio de endpoints dentro del briefing.
5. Después: semáforo ops real, MCP a Confluence/Jira/Datadog, alineado a IA-NOC.
