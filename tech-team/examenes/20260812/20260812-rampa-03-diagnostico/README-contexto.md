# Rampa diagnóstica 03 — DIAGNÓSTICO, NO GATE

**Esta corrida NO certifica nada.** Es la búsqueda de la rodilla para el encargo de
dimensionamiento (JF, 12-ago). `kind: diagnostico`, veredicto formal INVALID (k6 salió
con exit 99 = thresholds de dropped_iterations cruzados — esperado en overload). Las
fases hasta 50× son señal real del SUT; de 100× en adelante el instrumento también
colapsó y el número ya no describe al producto.

## La curva (chat, superficie dominante 60% del mix)

| Fase | Arrival factor | p50 | p95 | Rechazos admisión | Lectura |
|---|---|---|---|---|---|
| sustained | 10× | 901 ms | 977 ms | 0 | Sano — el stub pone 800 ms de piso, el producto agrega ~100 ms |
| burst | 25× | 2941 ms | 5252 ms | 6 | **RODILLA** — latencia ×3, la admisión C1 se activa |
| peak | 50× | 7048 ms | 60 001 ms (timeout) | 187 | Saturado — timeouts de cliente a 60 s |
| recovery | 100× | sin muestras | — | — | Instrumento saturado (VUs colgados en timeouts) |
| overload | 200× | sin muestras | — | — | Ídem — no vale como dato del SUT |

Referencia: el arrival factor multiplica la cadencia base del gate 125 (chat ≈ 6,25 req/s
a 10×; ≈ 15,6 req/s a 25×; ≈ 31 req/s a 50×, sobre la misma población de 125 identidades).

## Hallazgos

1. **Rodilla del SUT (ccx33, 8 vCPU ded./32 GB): entre 10× y 25× la carga de sede del
   gate 125.** Para el tech tree: 250 y 500 son 2× y 4× — ambos caen holgados dentro de
   la zona sana de ESTA máquina con latencias de stub. La ccx33 sobra para los tres gates;
   el dimensionamiento fino por tier puede bajar de instancia, no subir.
2. **La admisión C1 (#135) funciona bajo overload real**: 193 rechazos `saturated`
   contados en su bucket, cero mezclados con errores.
3. **Observación para el core: el rechazo tarda p50 6,0 s / p95 7,4 s / max 8,7 s** — la
   petición espera en cola antes del "busy". Un fast-fail temprano liberaría al cliente
   ~6 s antes. Es comportamiento de diseño (timeout de acquire), no un bug; queda como
   observación con evidencia.
4. **Límites del instrumento** (van al issue de deuda): por encima de 50× los VUs de chat
   quedan colgados en timeouts de 60 s y k6 dropea iteraciones (21 734 en total); el
   summary no parte `dropped_iterations` por fase; el orquestador trata exit 99 como fallo
   fatal aunque el summary quedó escrito y usable.

## Contexto de validez

- Producto main `52e694b` (mismo que el gate 02), stub realista (chat 800 ms,
  first-token 600 ms), SUT `ccx33` + generador `cpx42`, Hetzner hel1, egress bloqueado.
- Población: 125 identidades recicladas a mayor frecuencia — al SUT le llegan req/s, no
  usuarios distintos; la rampa varía exactamente eso.
- Historial: rampa 01 murió por OOM del generador (bug de sizing de VUs, arreglado),
  rampa 02 abortó en el smoke (cohorte 402, arreglado). Esta es la tercera y la que
  completó las 5 fases.
