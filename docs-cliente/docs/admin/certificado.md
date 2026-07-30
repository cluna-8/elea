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
que va a instalar en toda la flota es la de su instalación y no otra cosa: el instalador
la muestra en pantalla antes de continuar, y las dos deben coincidir carácter a carácter.

## Un equipo Windows: el camino recomendado

1. Copie la carpeta **completa** del kit al equipo (no sólo el `.bat`).
2. Haga **doble-click en `install-ca.bat`**.
3. Windows pedirá permiso de administrador: acéptelo. El proceso continúa en una ventana
   nueva.
4. Compare la **huella SHA-256** que aparece en pantalla con la que le dio su proveedor.
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

## Un equipo Windows por teléfono: la orden mínima

Si está guiando a alguien por teléfono y no tiene el kit a mano, esto es lo esencial. En
un **Símbolo del sistema abierto como administrador** (botón derecho → *Ejecutar como
administrador*; sin eso, el comando falla):

```
certutil -addstore -f Root C:\ruta\al\root.crt
```

`Root` es precisamente el almacén de raíces de confianza **del equipo**, y `-f` hace que
repetir el comando no dé problemas. Después, cierre y vuelva a abrir el navegador y
compruebe que la dirección de la pasarela ya no muestra el aviso.

Esta orden **sólo instala**: no comprueba nada. Cuando pueda, pase el kit completo y
ejecute `install-ca.bat` para tener la comprobación en verde.

## Toda la flota Windows: directiva de grupo

En un dominio de Active Directory, lo anterior no hace falta equipo por equipo. Una
directiva de grupo distribuye la CA a todas las máquinas del dominio:

1. Abra la **Consola de administración de directivas de grupo**, cree una directiva nueva
   (por ejemplo, *CA interna de la pasarela*) y edítela.
2. Vaya a **Configuración del equipo → Directivas → Configuración de Windows →
   Configuración de seguridad → Directivas de clave pública → Entidades de certificación
   raíz de confianza**.
3. Botón derecho sobre esa carpeta → **Importar** y seleccione `root.crt`.
4. **Vincule** la directiva a la unidad organizativa que contiene los equipos.
5. En un equipo de prueba, ejecute `gpupdate /force`, reinicie el navegador y compruebe
   que la pasarela abre sin avisos.

Es el camino preferible cuando hay más de un puñado de equipos: se aplica solo en cada
alta de máquina nueva y no depende de que nadie ejecute nada.

## Equipos Mac

Desde una terminal, en la carpeta del kit:

```
./install-ca-macos.sh
```

Pedirá la contraseña de administrador del Mac —el almacén del sistema la exige, igual que
en Windows— y termina con el mismo VERDE o ROJO. También es repetible sin efectos
secundarios.

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
