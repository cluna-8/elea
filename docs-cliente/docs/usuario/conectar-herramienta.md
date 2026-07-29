# Conectar una aplicación o herramienta

Además del Asistente Seguro, la pasarela expone una API HTTP para que sus propias
aplicaciones, scripts o automatizaciones consulten a los modelos de IA con la misma
protección de datos y la misma auditoría.

Esta página está pensada para perfiles técnicos de su organización.

## 1. Pida una llave virtual a su administrador

Las integraciones no usan su usuario y contraseña: usan una **llave virtual** (un token
`Bearer`). Solicítela a su administrador indicando:

- **Para qué la quiere** (la aplicación o el proceso que la va a usar).
- **A quién se imputa el consumo**: a usted o a su equipo.
- Una estimación de uso, para que dimensione los límites.

El administrador le entregará una cadena que empieza por `sk-basa-`.

!!! warning "La llave se muestra una sola vez"
    En el momento de generarla se ve completa y no se vuelve a mostrar. Guárdela en su
    gestor de secretos o en las variables de entorno de la aplicación — nunca en el
    código fuente ni en un repositorio. Si sospecha que se ha filtrado, pida al
    administrador que la revoque y le genere otra.

## 2. Haga su primera llamada

El endpoint de chat es `POST /api/v1/chat/completions` sobre la dirección de su
instalación. Sustituya `https://SU-INSTALACION` por la URL que le indique su
administrador.

```bash
curl -X POST https://SU-INSTALACION/api/v1/chat/completions \
  -H "Authorization: Bearer sk-basa-..." \
  -H "Content-Type: application/json" \
  -d '{
    "message": "¿Qué documentos necesito para exportar productos alimentarios a Francia?",
    "model": "camara-comercio-local"
  }'
```

Los dos campos del cuerpo son:

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `message` | Texto | La consulta, como una única cadena de texto. |
| `model` | Texto | El identificador del modelo a usar. |

!!! warning "El campo es `message`, en singular"
    No es `messages` con una lista de roles al estilo de otras APIs de IA. Esta API
    recibe **una cadena de texto** en el campo `message`.

!!! note "¿Qué valor pongo en `model`?"
    El identificador exacto de los modelos disponibles se lo indica su administrador; es
    el mismo nombre que aparece en el selector de modelo del Asistente Seguro.

## 3. Interprete la respuesta

La respuesta es un JSON con dos partes:

- **`response`** — el texto generado por el modelo, con sus datos personales ya
  restaurados, igual que en el Asistente Seguro.
- **`pipeline_metadata`** — la trazabilidad de esa petición: qué capas de protección se
  aplicaron, qué datos personales se enmascararon y el costo de la llamada.

Use `pipeline_metadata` en sus propios registros: le permite demostrar, petición a
petición, que la consulta pasó por la protección de datos antes de salir.

## 4. Tenga en cuenta los límites de la llave

Cada llave virtual lleva asociados sus propios límites, definidos por el administrador al
crearla:

| Límite | Qué controla |
| --- | --- |
| **RPM** | Peticiones por minuto. Valor de partida habitual: 60. |
| **TPM** | Tokens por minuto. Valor de partida habitual: 100 000. |
| **Presupuesto** | Gasto máximo en USD, con un período de reinicio (diario, semanal, mensual o anual). |

Consecuencias prácticas para su integración:

1. **Controle la concurrencia.** Si lanza procesos en paralelo o hace cargas masivas,
   puede superar el RPM o el TPM.
2. **Prevea el rechazo.** Implemente reintentos con espera creciente en lugar de
   reintentar de inmediato en bucle.
3. **Vigile el presupuesto.** Si se agota antes del reinicio del período, la llave deja
   de funcionar hasta que el administrador amplíe el límite o llegue el reinicio.

Si sus límites se quedan cortos para el caso de uso real, pida al administrador que los
ajuste — no cree llaves adicionales para repartir la carga.

## 5. Buenas prácticas de integración

- **Una llave por aplicación.** Así el consumo y la auditoría quedan atribuidos con
  claridad, y revocar una no tumba las demás.
- **Rote las llaves periódicamente** y revóquelas cuando el proyecto termine o cuando
  alguien deje el equipo.
- **No implemente su propio enmascarado** antes de llamar: la pasarela ya lo hace, y
  hacerlo dos veces degrada la calidad de las respuestas.
- **Conserve el `pipeline_metadata`** de cada llamada junto con sus propios registros de
  negocio.

!!! note "Herramientas de programación"
    Para asistentes de programación existe una superficie de conexión específica, con su
    propio modo de autenticación. Consulte a su administrador si necesita conectar una de
    esas herramientas.
