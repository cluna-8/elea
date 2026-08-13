# Examen de carga Fase 0 — 12-ago-2026 (La ITV 🚗)

**El primer número oficial de Guardian bajo carga existe y es verdad.** Gate 125 = **PASS**.

Cuatro corridas, en orden: tres del gate y una diagnóstica. Cada carpeta tiene
`verdict.json` (los 4 SLOs), `reporte.md` (lectura humana) y `fingerprint.json`
(qué se midió: producto, hardware, licencia).

| Run | Resultado | Qué dice |
|---|---|---|
| `20260812-g125-01` | **INVALID** | El harness se invalidó a sí mismo: un bug NUESTRO del wire de chat (mandaba formato OpenAI a un endpoint que espera otro) dejó el 60% de la carga sin medir. Lo cazamos a mano mirando la auditoría del producto a mitad del examen. Evidencia del hallazgo, no del producto. |
| `20260812-g125-02` | ✅ **PASS** | El examen de verdad, con el wire arreglado. Los 4 SLOs de oro en verde. **1506 eventos = 1506 filas** (paridad exacta), 0 auditoría perdida, 0 canarios fugados. Latencias: chat p95 **151 ms**, coding TTFT **650 ms**, 0 cortes de stream. |
| `20260812-g125-drill-01` | **INVALID** (a propósito) | El drill de saturación NO logró saturar: 0 rechazos con la ráfaga ×3 encima y el **SUT al 0,21% de CPU**. El instrumento se niega a certificar un drill que no ejercitó la defensa. El dato en sí: la ccx33 tiene muchísimo más techo que la carga de sede ×3. |
| `20260812-rampa-03-diagnostico` | **DIAGNÓSTICO** (no gate) | La búsqueda de la rodilla del encargo de dimensionamiento: **rodilla entre 10× y 25×** la carga de sede (chat p50 901→2941 ms, primeros rechazos de admisión en 25×; saturación plena en 50×). La admisión C1 funcionó bajo overload real (193 rechazos en su bucket) pero tarda ~6 s en rechazar. Ver `README-contexto.md` de la carpeta: NO es un número oficial. |

## Contexto que cada número necesita

- **Rótulo**: baseline 125 **post-#135** (con el fix de admisión C1 dentro).
- **Producto medido**: main `52e694b` (incluye #135 y #139).
- **Hardware**: SUT `ccx33` (8 vCPU dedicadas, 32 GB) + generador `cpx42`, ambos en Hetzner.
  Egress bloqueado por firewall; todo el "LLM" fue un stub local (0 costo de API).
  ⚠️ **La región no está respaldada por la evidencia**: los 6 `fingerprint.json` traen
  `"datacenter": null`. Se levantaron en `hel1` según el operador, pero el instrumento no
  lo capturó, así que aquí no se afirma. Deuda del harness, no del producto — ítem 8 del
  #168. Consecuencia: hoy el comparador daría por «legítima» una comparación entre
  datacenters distintos.
- **Licencia**: efímera de test (`itv-examen-2026`, 130 seats), muerta con la infra.
- **Corpus**: 100% sintético.

## Qué se llevó el día, además del PASS

El examen encontró **dos bugs en el examen mismo** (el wire de chat y el conteo de
bloqueos) y **cuatro hallazgos de producto** reportados con evidencia de run:
- **#157** — el 402 de presupuesto responde sin fila durable de auditoría.
- **#167** — el fail-closed del NLP bloquea tráfico legítimo en arranque-en-frío + ráfaga
  de logins (el "lunes 9am" de la sede); el sidecar estaba ocioso (0,02 s vs timeout de 2 s).
- **#166** — pedido de un marcador machine-readable de bloqueo (para C2).
- El 422 de FastAPI sin rastro (lo tomó el core como issue de producto).

El instrumento pasó por **tres rounds de gate adversarial del core en el mismo día** y salió
más fuerte de cada uno: wire real, contrato 4xx en las 4 superficies, prueba de humo antes
de generar carga, y precondiciones que ahora sí se verifican en vivo. PR #163 y #164
mergeados a main.

## Pendiente (encargo de JF, ya traducido por el core)

**Dimensionamiento por tier**: derivar de estas métricas qué instancia le corresponde a cada
gate (125/250/500) para que la carga muerda de verdad, y provisionar acorde al test — no la
ccx33 por defecto. El drill ×3 no encontró la rodilla; una rampa diagnóstica es el próximo
paso (y ya destapó que el propio generador necesita right-sizing para empujar tanta carga).
