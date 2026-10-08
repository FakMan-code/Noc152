# Motor visual-operacional (notas de diseño)

Notas internas. No es onboarding: el README cubre uso diario. El mapa 3D (`serve`) sigue siendo la UI principal.

## Contrato

NumPy no pinta la UI: calcula estado. Otra capa renderiza (ASCII hoy, Three.js en el mapa, Textual/Rich si alguna vez hay TUI).

```
collectors (ops, todavía no)  →  numpy state engine  →  renderer
                                      ↑
                         expediente (cobertura real)
```

Código: `okm/visual_state.py`. CLI de prueba: `python -m okm.cli board --workspace DIR [--mode operator|showcase]`.

Matriz por servicio (una fila):

`[availability, latency, errors, saturation, coverage, criticality]`

| Columna | Modo `operator` | Modo `showcase` |
|---|---|---|
| availability, latency, errors, saturation | `NaN` → `?` | serie sintética (seed 152) |
| coverage | del expediente (observed / total) | igual, real |
| criticality | `NaN` | un servicio “incidente” de demo |

- **operator** — no inventa latencia ni errores. Huecos explícitos.
- **showcase** — radar/heatmap/sparklines para presentaciones. El banner aclara que no es producción.

## Qué reforzar en pantalla

Jerarquía NOC, con o sin métricas:

1. Estado actual
2. Impacto / servicio afectado
3. Evidencia disponible
4. Acción sugerida (todavía no)
5. Qué falta (cobertura / `?`)

## Animaciones con significado

Solo estas, cuando haya series reales (hoy el showcase las imita):

| Efecto | Significa |
|---|---|
| Pulso | incidente nuevo o cambio de severidad |
| Onda | propagación estimada por dependencias |
| Desvanecimiento | alerta recuperada o dato envejecido |

No van: lluvia Matrix, glitch permanente, partículas al azar, arcoíris.

## Opciones (válidas con `NaN` / `?`)

1. Heatmap servicios × tiempo (Unicode o canvas).
2. Sparklines por servicio (`▁▂▃▄▅▆▇█`).
3. Radar de salud (distancia = cobertura o criticidad).
4. Topología 3D (`layout3d`) + pulso/onda sobre edges.
5. TUI Textual de 4 paneles (status, radar, incidente, cobertura) — no es el siguiente recorte.
6. Accesibilidad: `✓ ! × ?` además del color; `--no-motion`; fallback ASCII.

Siguiente recorte útil: proyectar la misma matriz (con `?`) en un rincón de `serve`, no armar una TUI aparte.
