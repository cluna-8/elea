# Verificación local del instalador con `ELEA_REDIRECT=1` (T102) — 2026-10-07

Evidencia **sin contenido** (sin pedidos, sin contraseñas, sin llaves): comandos, códigos, tiempos y nombres. El detalle de la corrida de contenedores está en
`EVIDENCIA-T102.md` del repositorio `cluna-8/elea-installer` (rama `cluna-8/057-runbook-vpn`, commit `00288d7`); acá queda lo que la spec pide de T102 y qué falta.

Instalación de prueba: la PC del owner, directorio propio fuera de cualquier instalación del owner, imágenes del candidato construidas en local (`2026-10-07` y `2026-10-07-ext`), código de la rama final de la 057.

## Lo verificado (🟢)

| Qué pide T102 | Resultado | Fuente |
|---|---|---|
| Instalador con `ELEA_REDIRECT=1`: imágenes `-ext`, entorno con modo 600 fuera del repo, recreación de motor, backend y panel | `./install.sh` completo en 96 s; las tres imágenes terminan en `-ext`; `~/.config/elea/redirect.env` en 600 | `EVIDENCIA-T102.md` §2 |
| Seeds cargados al arrancar (S16): `/api/v1/redirect/health` en 200 al primer intento (T104/T095; QA v2 N1) | 200 `{"status":"ok"}` al primer intento; catálogo de ejemplo sembrado (4 destinos de Azure) | §2 |
| `/api/v1/internal/*` ⇒ 404 desde otra máquina de la LAN con la variante `-ext` (QA v2 N2) | 404 desde el servidor y desde la IP de la LAN; `/api/v1/redirect/health` 200 | §2 (Paso 7 b) |
| Dos revisiones de `alembic`, las dos `(head)` | verificado | §2 |
| Vuelta atrás de nivel 1 (apagar y volver a encender) | apagar: 78 s de reloj, `/health` 53 s caído; encender: 83 s, 6,2 s caído; los 4 destinos siguen | §3 |
| Cambiar la credencial de Azure del `.env` recrea motor y backend y conserva las `-ext` | verificado | §4 |
| Claude Desktop contra la pasarela local con destino Azure y la postura por defecto real | Conexión por gateway (URL `/api/v1/gw`, `bearer`, llave estática, descubrimiento); chat con `haiku` → `gpt-5.4-mini`, `sonnet` → `gpt-5.1-chat` y `opus` → `gpt-5.6-luna`; cambio de destino de `sonnet` a `gpt-5.6-luna` en *Reglas* confirmado en logs y auditoría; DNI enmascarado hacia Azure; Cowork con PDF y presentación; SVG; lectura de imágenes (`haiku`, `opus`, `sonnet` tras marcar *Imágenes*); llave con 1 000 000 tpm / 120 rpm por *Editar límites*; esfuerzo ajustado (`gpt-5.1-chat` solo `medium`); etiqueta «id pedido»; credencial de Azure del catálogo con `api_version` `2025-04-01-preview`; alta de modelos y ficha | prueba en vivo del owner, 7-oct-2026 (registrada en `CHANGELOG.md` §4d y en `docs/docs/integrations/claude-desktop.md`) |

## Lo que NO se probó (por eso T102 sigue abierta)

- El respaldo de T094: borrar la fila de región **por SQL en la base de prueba** y reiniciar sin `REDIRECT_SEED_FILES` (esperado: hacia Azure en EE. UU., 403 por quedar fuera de `region_codes`; `/api/v1/redirect/health` 503).
- El arranque que falla de T088 (migración rota a propósito).
- La vuelta atrás de **nivel 2** (restaurar el respaldo con las imágenes base).
- Claude Code (CLI) y la superficie *Code* de Claude Desktop contra la pasarela local.
- El kit `managed-settings.json` instalado en una PC; un destino que no sea Azure (OpenRouter/Kimi); los grupos.
- La región real del recurso de Azure (US) está **por confirmar** en el portal; la ficha la carga cumplimiento.
