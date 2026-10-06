# Eleia — Ingreso con cuenta corporativa de Microsoft (Entra ID)

**Qué necesitamos de Elea para activarlo**

**Fecha**: 23 de septiembre de 2026

## Qué vamos a hacer

Vamos a sumar a Eleia Hub un botón **"Ingresar con Microsoft"**. Cada persona entra con la misma
cuenta que usa en Windows y Office, sin otra contraseña más.

- **Nada de lo que funciona hoy cambia.** El ingreso con usuario y contraseña sigue disponible
  siempre. Cada persona conserva su rol, su equipo, su presupuesto y sus espacios.
- **Se instala apagado.** Después de la actualización nadie ve cambios hasta que un administrador
  de Elea lo enciende desde el panel Eleia Guardian.
- **Se puede apagar en segundos** desde el mismo panel, y se puede volver a la versión anterior si
  hiciera falta. La actualización no modifica la base de datos.
- **Lo prueba primero un grupo piloto** de 2 o 3 personas y después se habilita para todos.
- **La configuración se hace en el servidor de Elea.** El secreto de la aplicación lo carga el IT
  de Elea directamente en el panel, así que nunca tiene que enviárnoslo.

## Lo que necesitamos

### 1. Confirmar cómo está el directorio

- [ ] **¿El Active Directory de Elea está sincronizado con Microsoft Entra ID** (Entra Connect o
      Cloud Sync, lo habitual si usan Microsoft 365 u Outlook en la nube)? Si **no** lo está,
      avísennos antes de seguir: cambia la forma de conectarlo.
- [ ] **¿Con qué dirección inicia sesión cada persona en Microsoft?** (el "nombre de usuario" o
      UPN, por ejemplo `nombre.apellido@elea.com`). Necesitamos saber si coincide con el email
      con el que cada usuario está dado de alta en Eleia. Así reconocemos a cada persona y no
      creamos cuentas duplicadas.

### 2. Registrar la aplicación en Entra ID (lo hace un administrador de Entra de Elea, ~30 min)

En el portal de Entra: **App registrations → New registration**.

| Campo | Valor |
|---|---|
| Nombre | `Eleia` |
| Tipos de cuenta admitidos | **Solo cuentas de este directorio** (un solo tenant) |
| URI de redirección | Plataforma **Web** (no "SPA"): `https://<nombre-del-servidor>/sso/callback`, con el nombre del punto 3 y sin barra final |

Después:

- [ ] **Permisos de API**: Microsoft Graph, permisos **delegados** `openid`, `profile`, `email`
      (y `User.Read`, que viene por defecto). Otorgar **consentimiento de administrador**.
- [ ] **Certificados y secretos → Nuevo secreto de cliente**. Anotar la **fecha de vencimiento**
      (recomendado: 12 o 24 meses). **El valor del secreto no nos lo envíen**: lo carga el IT en
      el panel Eleia Guardian el día de la activación.
- [ ] *(Recomendado)* En **Aplicaciones empresariales → Eleia → Propiedades**, activar
      **"¿Asignación requerida?"** y asignar un grupo, por ejemplo `Eleia-Usuarios`. Así solo
      pueden entrar las personas de ese grupo.
- [ ] Si Elea tiene **MFA o acceso condicional**, se aplica automáticamente a Eleia. No hace falta
      configurar nada de nuestro lado.

**Qué nos envían de este punto** (no son secretos):

- **Directory (tenant) ID**
- **Application (client) ID**
- Fecha de vencimiento del secreto

### 3. Red y certificado

Microsoft solo permite volver a una dirección **segura (https)**. Hoy Eleia se usa por
`http://172.16.0.120`, así que hace falta:

- [ ] **Un nombre interno** para el servidor, por ejemplo `eleia.elea.local` o
      `eleia.elea.com.ar`, que apunte a `172.16.0.120` en el DNS de Elea.
- [ ] **Un certificado** para ese nombre, emitido por la CA interna de Elea (que ya confíen las PC
      de la empresa) o un certificado público. Nos envían el certificado y su clave privada **por
      un canal seguro**, o los copia el IT al servidor.
- [ ] **Salida a internet por HTTPS (puerto 443)** desde el servidor `172.16.0.120` hacia
      `login.microsoftonline.com`. El servidor la usa para validar el ingreso.
- [ ] Que las PC de los usuarios lleguen al servidor por ese nombre en el puerto 443.

### 4. Piloto y coordinación

- [ ] **2 o 3 personas piloto** con usuario activo en Eleia, idealmente con roles distintos, que
      puedan probar en el día.
- [ ] **Listado de usuarios**: su dirección de inicio de sesión en Microsoft (UPN), para cruzarla
      con los usuarios de Eleia.
- [ ] **Una ventana de mantenimiento de ~1 hora** para instalar la actualización (las sesiones
      abiertas de Eleia se cierran y hay que volver a ingresar).
- [ ] **Un contacto del IT** disponible durante la instalación y el día del piloto.
- [ ] Acceso al servidor como en las actualizaciones anteriores (VPN).

## Cómo sigue

1. **Nosotros**: desarrollamos y probamos todo en nuestro entorno, con un directorio de prueba.
2. **Elea, en paralelo**: completa los puntos 1 a 4 y nos envía los datos.
3. **Juntos, en la ventana**: instalamos la actualización con la función apagada y verificamos que
   todo funciona igual que antes.
4. **Día de la activación**: el IT de Elea carga los datos en el panel y enciende la función;
   prueba el grupo piloto; si todo está bien, se habilita para todos.

Ante cualquier duda sobre estos pasos, coordinamos una llamada corta con el administrador de Entra
de Elea.
