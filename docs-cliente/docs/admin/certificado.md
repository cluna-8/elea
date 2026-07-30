# Confiar el certificado en los equipos

La pasarela se publica por **https**. Cuando la instalación no usa un dominio público
sino una dirección de su red interna, el certificado que presenta lo emite una
**autoridad de certificación propia de la instalación**: una CA que existe sólo para su
organización y que, por definición, ningún navegador conoce de fábrica.

Hasta que cada equipo confíe en esa CA, dos cosas no funcionan:

- El navegador muestra el aviso de **sitio no seguro** cada vez que alguien entra al panel.
- La **[extensión del navegador](../usuario/extension.md) no conecta**. Exige `https`
  válido para cualquier dirección que no sea el propio equipo, así que un certificado no
  confiado la deja fuera de juego por completo.

Por eso instalar la CA en los puestos **forma parte de la puesta en marcha**, no es un
retoque opcional posterior.

!!! danger "El doble-click sobre el `.crt` NO sirve"
    Es el error que más tiempo cuesta. Al abrir el fichero con doble-click, el asistente
    de Windows instala el certificado **para el usuario actual**, no para el equipo, y
    termina diciendo «importación correcta». No hay ningún mensaje de error: el
    certificado queda en un almacén que el navegador **no** consulta para decidir en qué
    autoridades confía, y el aviso de sitio no seguro sigue apareciendo.

    El certificado tiene que ir al almacén **«Entidades de certificación raíz de
    confianza» del equipo local**. Ése es el único paso que importa, y es el que hacen
    los procedimientos de esta página.

## Qué le entrega su proveedor

Una carpeta —el *kit de confianza*— con estos ficheros:

| Fichero | Para qué |
| --- | --- |
| `root.crt` | La CA raíz de su instalación. Es lo que hay que instalar. |
| `install-ca.bat` | Lo que se ejecuta en Windows (doble-click). |
| `install-ca.ps1` | El instalador propiamente dicho; lo llama el `.bat`. |
| `install-ca-macos.sh` | El equivalente para equipos Mac. |
| `gateway-url.txt` | La dirección de su pasarela, para que la comprobación final se haga sola. |

Además, y **por un canal distinto** del que lleva la carpeta (una llamada, por ejemplo),
su proveedor le da la **huella SHA-256** de `root.crt`. Sirve para comprobar que la CA
que va a instalar en toda la flota es la de su instalación y no otra cosa.

!!! warning "La huella no es un trámite: es la comprobación que lo protege"
    Instalar una CA en el almacén raíz de un equipo significa que ese equipo **acepta
    como válido cualquier certificado que esa CA firme** — para cualquier sitio, en
    todos los navegadores. Si el `root.crt` que le llegó no es el de su instalación
    (una copia vieja, el de otra organización, o un fichero alterado por el camino),
    el equipo queda expuesto y **no hay ningún síntoma visible**: todo parece
    funcionar.

    Cotejar la huella por un canal distinto del que trajo el fichero es lo único que
    lo detecta. Por eso los instaladores **no tocan el almacén del equipo hasta que
    la huella queda verificada**: o la confirma usted en pantalla, o se la pasa por
    parámetro para que la comprueben ellos.

## Un equipo Windows: el camino recomendado

1. Copie la carpeta **completa** del kit al equipo (no sólo el `.bat`).
2. Haga **doble-click en `install-ca.bat`**.
3. Windows pedirá permiso de administrador: acéptelo. El proceso continúa en una **ventana
   nueva**, y es en ésa donde hay que mirar.
4. El instalador muestra la **huella SHA-256** y **se detiene a preguntar**. Compárela,
   carácter a carácter, con la que le dio su proveedor:
    - **coinciden** → escriba `SI` y pulse INTRO;
    - **no coinciden**, o no tiene con qué compararla → cualquier otra respuesta (o
      INTRO a secas) **cancela sin instalar nada**, que es la respuesta por defecto.
      Avise a su proveedor antes de repetir.
5. Espere al resultado final.

El instalador termina con un mensaje que no admite interpretación:

- **VERDE — TODO CORRECTO.** No sólo instaló el certificado: abrió una conexión real
  contra su pasarela y comprobó que el equipo la valida. Ya puede abrir el panel y
  conectar la extensión.
- **ROJO — NO VERIFICADO.** Indica en qué etapa falló y qué revisar. Envíe esa pantalla
  completa a su soporte técnico.

Puede ejecutarlo **las veces que quiera**: si el certificado ya estaba instalado, lo
detecta, no lo duplica y pasa directamente a comprobar.

!!! tip "Si prefiere indicarlo todo a mano"
    Desde una consola, sin depender del contenido de `gateway-url.txt`:

    ```
    install-ca.bat -Url https://<dirección-de-su-pasarela>
    ```

### Si no hay nadie delante: pásele la huella

Cuando el instalador se lanza sin una persona que pueda contestar —un script de
arranque, su herramienta de gestión de flota, una tarea programada— la pregunta por
pantalla no serviría de nada. En ese caso se le pasa **la huella que se espera**, y es
el propio instalador el que la comprueba:

```
install-ca.bat -NoPause -Fingerprint <huella-SHA-256-que-le-dio-su-proveedor>
```

- Si la huella del fichero **coincide**, instala y verifica sin preguntar nada.
- Si **no coincide**, no instala nada y termina con **código de salida 4**. En un equipo
  al que llegó el fichero equivocado, el despliegue se detiene ahí en vez de dejar una
  CA ajena instalada en silencio.

La huella se acepta tal como se la hayan dado: con `:` o sin él, en mayúsculas o en
minúsculas.

!!! danger "`-NoPause` por sí solo ya no instala"
    `-NoPause` significa «no hay nadie delante». Sin `-Fingerprint`, el instalador
    **aborta** en lugar de instalar a ciegas. Si ya cotejó la huella por otro medio y
    quiere saltarse la comprobación asumiendo la responsabilidad, existe
    `-AcceptFingerprint` — pero entonces la única salvaguarda del kit queda en su
    palabra, no en una comprobación.

Códigos de salida, por si los recoge su herramienta de despliegue: `0` correcto ·
`1` la comprobación contra la pasarela falló · `2` error de entrada · `3` no se pudo
elevar a administrador · `4` **huella no verificada, no se instaló nada**.

## Un equipo Windows por teléfono: la orden mínima

Si está guiando a alguien por teléfono y no tiene el kit a mano, esto es lo esencial. En
un **Símbolo del sistema abierto como administrador** (botón derecho → *Ejecutar como
administrador*; sin eso, el comando falla).

**Primero la huella** — este comando no instala nada, sólo la calcula:

```
certutil -hashfile C:\ruta\al\root.crt SHA256
```

Compárela con la que le dio su proveedor. **Si no coincide, pare aquí.** Sin este paso
está instalando una CA sin saber cuál es, que es justo lo que el instalador del kit no
le deja hacer.

**Y sólo entonces, la instalación:**

```
certutil -addstore -f Root C:\ruta\al\root.crt
```

`Root` es precisamente el almacén de raíces de confianza **del equipo**, y `-f` hace que
repetir el comando no dé problemas. Después, cierre y vuelva a abrir el navegador y
compruebe que la dirección de la pasarela ya no muestra el aviso.

Estas órdenes **instalan y nada más**: no comprueban que el equipo confíe de verdad en la
pasarela, y la comparación de la huella queda en sus manos. Cuando pueda, pase el kit
completo y ejecute `install-ca.bat`, que hace las dos cosas.

## Toda la flota Windows: directiva de grupo

En un dominio de Active Directory, lo anterior no hace falta equipo por equipo. Una
directiva de grupo distribuye la CA a todas las máquinas del dominio:

1. **Coteje la huella del `root.crt` que va a importar.** Éste es el momento en que se
   decide en qué confía toda la flota, y la consola de directivas **no le va a
   preguntar nada**: lo que importe aquí se instala solo en cada equipo del dominio. En
   una consola:

    ```
    certutil -hashfile C:\ruta\al\root.crt SHA256
    ```

    Compárela con la que le dio su proveedor por el canal aparte. Si no coincide, **no
    siga**.

2. Abra la **Consola de administración de directivas de grupo**, cree una directiva nueva
   (por ejemplo, *CA interna de la pasarela*) y edítela.
3. Vaya a **Configuración del equipo → Directivas → Configuración de Windows →
   Configuración de seguridad → Directivas de clave pública → Entidades de certificación
   raíz de confianza**.
4. Botón derecho sobre esa carpeta → **Importar** y seleccione `root.crt`.
5. **Vincule** la directiva a la unidad organizativa que contiene los equipos.
6. En un equipo de prueba, ejecute `gpupdate /force`, reinicie el navegador y compruebe
   que la pasarela abre sin avisos.

Es el camino preferible cuando hay más de un puñado de equipos: se aplica solo en cada
alta de máquina nueva y no depende de que nadie ejecute nada.

!!! tip "Si en vez de importar el certificado prefiere repartir el instalador"
    Algunas organizaciones distribuyen el kit con un script de inicio de la propia
    directiva o con su herramienta de gestión de flota, en lugar de importar el
    `root.crt` en la GPO. Es igual de válido, **siempre que lleve la huella**:

    ```
    install-ca.bat -NoPause -Fingerprint <huella-SHA-256> -Url https://<su-pasarela>
    ```

    Es la única forma desatendida que conserva la comprobación: cada equipo verifica el
    fichero que le llegó antes de instalarlo, y el que reciba otro **aborta con código
    4** en lugar de confiar en una CA que nadie miró. Además, a diferencia de la
    importación por GPO, deja comprobado con una conexión real que el puesto llega a la
    pasarela y la valida.

## Equipos Mac

Desde una terminal, en la carpeta del kit:

```
./install-ca-macos.sh
```

Muestra la huella SHA-256 y **se detiene a preguntar**, igual que en Windows; sólo
después pide la contraseña de administrador del Mac —el almacén del sistema la exige— y
termina con el mismo VERDE o ROJO. Que la pregunta vaya **antes** que la contraseña es a
propósito: si la huella no cuadra, se cancela sin haber elevado privilegios.

Para despliegue por MDM o por script, con la huella por parámetro y sin preguntas:

```
./install-ca-macos.sh --fingerprint <huella-SHA-256>
```

También es repetible sin efectos secundarios.

## Firefox

Firefox no usa el almacén de certificados del sistema: mantiene el suyo propio. Un equipo
puede quedar perfectamente configurado en Edge y Chrome y seguir dando el aviso en
Firefox.

Los instaladores de esta página **ya lo resuelven**: activan la directiva de Firefox que
le hace leer las autoridades del equipo. Lo único que hace falta es **cerrar Firefox por
completo y volver a abrirlo** para que la tome. Si en su organización Firefox se gestiona
con sus propias directivas, indique a quien las administre que debe estar activada la
opción de **importar las raíces de la empresa**.

## Si algo sigue fallando

| Síntoma | Qué suele ser | Qué hacer |
| --- | --- | --- |
| El aviso de sitio no seguro sigue apareciendo tras el doble-click sobre el `.crt` | El certificado se instaló para el usuario, no para el equipo | Ejecute `install-ca.bat`; es exactamente lo que corrige |
| El instalador dice **«LA HUELLA NO COINCIDE»** y termina sin instalar (código 4) | El `root.crt` que hay en ese equipo no es el de su instalación: copia vieja, el de otra organización, o un fichero alterado por el camino | **No lo instale.** Pida a su proveedor que le reenvíe la CA y vuelva a cotejar la huella por el canal aparte |
| El instalador dice **«modo desatendido sin huella esperada»** y no instala | Se lanzó con `-NoPause` (sin nadie que pueda confirmar) y sin `-Fingerprint` | Añada `-Fingerprint <huella>` al comando de su herramienta de despliegue |
| El instalador termina en ROJO en la etapa «conexión» | No es un problema de confianza: el equipo no llega a la pasarela | Revise la dirección y que la red permita el acceso |
| El instalador termina en ROJO en la etapa «validación» | La CA instalada no es la de esta instalación, o la dirección no coincide con el nombre del certificado | Coteje la huella SHA-256; entre por la dirección exacta para la que se emitió |
| Funciona en Edge y Chrome, pero no en Firefox | Firefox no había reiniciado tras activarse la directiva | Cierre Firefox del todo y vuelva a abrirlo |
| La extensión del navegador no conecta y la dirección es correcta | El equipo aún no confía en el certificado | Ejecute el instalador en ese equipo y compruebe el verde |
| Todo dejó de funcionar de golpe, en todos los equipos a la vez | La CA de la instalación pudo caducar | Contacte con su soporte: hay que reemitirla y volver a distribuirla |

!!! note "Cuando cambie la dirección de la pasarela"
    Si la instalación pasa a publicarse en otra dirección o con otro nombre, el
    certificado del servidor tiene que reemitirse para ese nombre. La CA instalada en los
    equipos **sigue valiendo**: no hay que repetir esta distribución, sólo comprobar de
    nuevo con `install-ca.bat -Url https://<dirección-nueva>`.

## Relacionado

- [Primeros pasos como administrador](index.md) — el resto de la puesta en marcha.
- [Extensión del navegador](../usuario/extension.md) — la superficie que exige este paso.
- [Conectar tu herramienta de IA](../usuario/conectar-herramienta.md) — la dirección de
  la pasarela que usan las herramientas es la misma que se verifica aquí.
