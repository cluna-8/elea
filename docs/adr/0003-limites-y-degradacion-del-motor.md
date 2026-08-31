# ADR-0003: Qué protege el tope de admisión y cuándo el producto puede cambiar de modelo

**Fecha:** 2026-08-12 · **Estado:** aceptado
**Decisores:** JF (issue #134, puntos ② y ③) · propuesto desde el nodo C1 (PR #135, issue #151)

## Contexto

El 30-jul la sede quedó muda ~10 minutos: el runtime del modelo local serializa las
generaciones y encola FIFO sin tope, cada chat en vuelo retenía su conexión de Postgres
mientras esperaba, y al agotarse el pool el worker dejó de contestar TODO —login, health,
panel—, aunque lo único lento era el modelo. El fix del nodo C1 (PR #135) corta en admisión:
un tope de pedidos en vuelo hacia el motor y un 503 honesto, auditado y con cabecera propia
para el que no entra.

Al escribir ese fix quedaron dos preguntas que no son técnicas sino de producto, y que se
sellan acá porque de otro modo las decide sin querer el próximo que toque una config: **hasta
dónde llega el tope** (¿también al tráfico que no usa el motor local?) y **cuándo el producto
puede servir una respuesta de un modelo distinto al pedido**. La segunda venía marcada como
«decisión de JF» en el `config.yaml` desde el spike 019, con el mecanismo ya construido en la
feature 010 (fallback por modelo, configurable desde el panel).

## Decisión

**(a)** El tope de admisión **gatea el camino al MOTOR, no todo el tráfico**: el **passthrough
de suscripción queda deliberadamente SIN tope**. Lo que se protege es el producto entero —ése
fue el daño del 30-jul—, y para eso alcanza con acotar el único camino que lo puede tumbar: el
que retiene conexiones esperando una generación. El upstream del passthrough es capacidad del
proveedor —escala solo y trae sus propios 429/529—, no la cola local que causó el incidente.

**(b)** El producto cambia de modelo **sólo donde hay un fallback configurado para ese
modelo** (feature 010: `router_settings.fallbacks`, editable desde el panel). Sin fallback
configurado, el error viaja **explícito** al cliente. Queda prohibida cualquier degradación
inventada — silenciosa o no— hacia un modelo que nadie eligió.

## Alternativas consideradas

- **(a) Gatear también el passthrough**: descartada — agregaría un rechazo nuestro sobre un
  upstream que no está saturado; convertiría capacidad ajena disponible en un 503 propio.
- **(a) No gatear nada y subir el pool de Postgres**: descartada — mueve el techo, no lo
  crea; con la cola sin tope el pool se vuelve a agotar, sólo que más tarde y más caro.
- **(b) Fallback global cloud→local por defecto**: descartada — es exactamente la sustitución
  silenciosa que hace impresentable un producto de auditoría: la respuesta conserva el nombre
  del modelo pedido y el cliente no se entera de que le contestó otro.
- **(b) Prohibir todo fallback**: descartada — el mecanismo por modelo es una función vendida
  (010) y la elige el operador con nombre y apellido; el problema nunca fue el fallback, fue
  el fallback que nadie configuró.

## Consecuencias

- El 503 de saturación (`X-Sentinel-Rejected: saturated`, fila `rejected_saturated`) es un
  síntoma **del motor**. Ver un pico de esos rechazos en el passthrough sería un bug, no una
  saturación.
- El tope del motor local se configura **por encima** del total que el backend puede admitir
  (`max_parallel_requests` del deployment > tope por proceso × workers), para que el primero
  en decir que no sea siempre el backend: su rechazo es honesto y auditado; el del motor es
  un error opaco. `backend/tests/contract/test_catalogo_motor_paralelismo.py` lo fija para los
  valores que se EMBARCAN (20 > 8 × 2); con el tope env-tuneable, subirlo sin subir el del
  motor invierte la relación **en silencio**, así que el co-cambio queda documentado en la
  descripción de `SENTINEL_ENGINE_MAX_CONCURRENCY` (`.env.example`). Una guarda automática exigiría
  acoplar el backend a un valor del catálogo del motor: se diseña con el tuning del gate 250.
- Los reintentos del router contra el runtime local van en **0** (decisión ②): reintentar
  contra una cola FIFO es multiplicar por tres el trabajo que ya no entra. Los reintentos son
  una capa distinta de los fallbacks: con `num_retries: 0`, un modelo con fallback
  configurado sigue cayendo a él tras el único intento fallido.
- Un fallback nuevo se agrega desde el panel y queda escrito en la config del cliente: es
  auditable quién lo puso.
- **Sembrar fallbacks por default en una plantilla de perfil queda prohibido** (JF, 12-ago):
  las plantillas van limpias porque los modelos del cliente **no se conocen de antemano** —
  configurarlos es un acto explícito del operador AL INSTALAR, no un default que viaja en el
  repo.
- Matiz de la misma decisión: un **wizard o instalador SÍ puede PROPONER** configuraciones de
  fallback para que el operador las confirme. Proponer ≠ sembrar: lo que la regla prohíbe es el
  fallback que queda activo sin que nadie lo haya elegido.
