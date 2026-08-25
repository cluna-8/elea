import React, { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { authStorage, SessionUser } from "../services/auth";
import { Card } from "../components/ui";

interface SsoCallbackPageProps {
  /** Sesión ya guardada (mismo `authStorage` que el login local) — el llamador sólo
   *  actualiza el estado de React y navega adonde va cualquier usuario recién logueado. */
  onSuccess: (user: SessionUser) => void;
  /** 4xx del callback (o un `code`/`state` ausente) — el llamador vuelve al login con este
   *  mensaje. El formulario de usuario/contraseña sigue funcionando (FR-009). */
  onError: (message: string) => void;
}

/** Lo que el directorio contesta cuando NO emite un código, mapeado a lo único que le sirve a
 *  quien está mirando la pantalla: **qué hacer ahora**. Los códigos son los de OAuth2
 *  (RFC 6749 §4.1.2.1) y OIDC (§3.1.2.6) — no son de Entra, así que este mapa sirve igual para
 *  el próximo proveedor.
 *
 *  Hasta #294 los cuatro casos de abajo mostraban el MISMO texto («No se recibió una respuesta
 *  válida de Microsoft. Intente iniciar sesión nuevamente.»), y ese consejo sólo es correcto en
 *  uno: en los otros manda a repetir un login que va a fallar igual. El motivo venía en el query
 *  string y se descartaba sin leerlo — y como la pantalla nunca llama al backend, tampoco
 *  quedaba en los registros del servidor. Se perdía del todo.
 */
const ACCION_POR_CODIGO: Record<string, string> = {
  // El usuario canceló, O un administrador tiene que aprobar la aplicación: el directorio usa
  // el mismo código para las dos cosas, así que el texto no puede elegir por él.
  access_denied:
    "El directorio no autorizó el acceso. Si no cancelaste vos, la aplicación necesita que " +
    "un administrador del directorio la apruebe una vez.",
  // Consentimiento: NO se arregla reintentando. Es un clic de un administrador, una sola vez.
  consent_required:
    "La aplicación todavía no está aprobada en el directorio. Un administrador tiene que " +
    "autorizarla una vez; reintentar no alcanza.",
  interaction_required:
    "El directorio necesita un paso más de tu parte (registrar el segundo factor o volver a " +
    "identificarte). Completalo en la pantalla del directorio y reintentá.",
  login_required:
    "El directorio pidió iniciar sesión de nuevo. Reintentá el acceso.",
  // Los tres de abajo son configuración del REGISTRO de la aplicación: no los arregla el usuario.
  invalid_request:
    "El pedido al directorio no es válido: es la configuración del registro de la aplicación, " +
    "no tu cuenta.",
  unauthorized_client:
    "El directorio no reconoce a esta aplicación como autorizada: es la configuración del " +
    "registro, no tu cuenta.",
  invalid_scope:
    "El directorio rechazó los permisos que pide la aplicación: es la configuración del " +
    "registro, no tu cuenta.",
  server_error:
    "El directorio tuvo un problema propio. Reintentá en unos minutos.",
  temporarily_unavailable:
    "El directorio no está disponible en este momento. Reintentá en unos minutos.",
};

/** Forma admitida para el código que llega del directorio antes de pintarlo. React escapa el
 *  texto, así que esto no es contra XSS: es contra un valor larguísimo o con saltos de línea
 *  reventando el banner de la pantalla de acceso.
 *
 *  Ojo con el gemelo de este guard en el backend: en Python `$` matchea TAMBIÉN justo antes de
 *  un `\n` final y hay que usar `fullmatch`. En JavaScript, sin el flag `m`, `$` ancla de
 *  verdad al final de la cadena — acá `^…$` alcanza. No "unificar" los dos a ciegas. */
const FORMA_CODIGO = /^[A-Za-z0-9_.-]{1,40}$/;

/** El código `AADSTS…` que Entra mete DENTRO de la descripción larga. Es lo único de esa
 *  descripción que se pinta: el resto lo redacta el directorio en texto libre y suele traer
 *  identificadores de la organización y de la persona (Trace ID, Correlation ID) que no tienen
 *  por qué terminar en una captura de pantalla pegada en un ticket. El código, en cambio, es
 *  exactamente lo que hay que pasarle a quien administra el directorio. */
const FORMA_AADSTS = /AADSTS\d{3,7}/;

export function mensajeDelDirectorio(codigoCrudo: string, descripcion: string | null): string {
  const codigo = FORMA_CODIGO.test(codigoCrudo) ? codigoCrudo : null;
  const aadsts = descripcion ? (descripcion.match(FORMA_AADSTS) || [null])[0] : null;

  const accion = (codigo && ACCION_POR_CODIGO[codigo]) ||
    "El directorio no completó el acceso.";
  const referencia = [codigo, aadsts].filter(Boolean).join(" · ");

  // El fallback local NO es un consuelo: es la regla FR-009. Se nombra siempre, porque en la
  // mitad de estos casos la persona no puede hacer nada por su cuenta con el directorio.
  const cierre = "Podés entrar con usuario y contraseña mientras tanto.";
  return referencia ? `${accion} ${cierre} (${referencia})` : `${accion} ${cierre}`;
}

/**
 * Pantalla de retorno del IdP (paso 3-4 del flujo SSO, spec 017 US2). Se registra como
 * redirect URI `/sso/callback` en el proveedor. No hay router de URLs en esta SPA (todas
 * las demás páginas viven en el estado de `App`, no en la barra de direcciones) así que
 * esto no es una ruta de un router — es una pantalla que `App` monta cuando detecta
 * `window.location.pathname === "/sso/callback"`, exactamente el patrón que ya usa el
 * resto del panel. El Caddy del frontend sirve la SPA con `try_files {path} /index.html`
 * (deploy/docker/Caddyfile.frontend), así que la navegación completa que hace Microsoft al
 * volver acá igual carga este código.
 *
 * `code`/`state` vienen en el query string (nunca el token: el fetch del paso 4 es quien
 * lo trae, en el cuerpo). El guard de `consumedRef` evita un segundo intercambio si
 * StrictMode reinvoca el efecto en dev — el `code` es de un solo uso del lado del IdP/backend.
 *
 * Cuando el directorio NO emite un código, en cambio, manda `error`/`error_description` por el
 * mismo query string: eso es lo que lee `mensajeDelDirectorio` (#294). Es la única oportunidad
 * de capturarlo — esta pantalla no llama al backend en ese camino, así que si no se lee acá no
 * queda en ningún registro del servidor.
 */
export const SsoCallbackPage: React.FC<SsoCallbackPageProps> = ({ onSuccess, onError }) => {
  const [processing, setProcessing] = useState(true);
  const consumedRef = useRef(false);

  useEffect(() => {
    if (consumedRef.current) return;
    consumedRef.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const errorDelIdP = params.get("error");

    // Se mira ANTES que `code`/`state`: cuando el directorio devuelve un error no manda código,
    // así que el guard de abajo lo atrapaba primero y el motivo moría acá (#294).
    if (errorDelIdP) {
      const mensaje = mensajeDelDirectorio(errorDelIdP, params.get("error_description"));
      setProcessing(false);
      // `App` va a reescribir la URL a "/" enseguida y el query string se pierde. Queda acá
      // para quien esté mirando la consola del navegador durante un diagnóstico — el código y
      // el AADSTS, no la descripción larga, por lo mismo que no se pintan.
      console.warn("[sso] el directorio devolvió un error en el retorno:", mensaje);
      onError(mensaje);
      return;
    }

    if (!code || !state) {
      setProcessing(false);
      onError("No se recibió una respuesta válida de Microsoft. Intente iniciar sesión nuevamente.");
      return;
    }

    api
      .exchangeSsoCallback(code, state)
      .then((res) => {
        authStorage.save(res.access_token, res.user as SessionUser);
        setProcessing(false);
        onSuccess(authStorage.getUser() as SessionUser);
      })
      .catch((err: any) => {
        setProcessing(false);
        onError(err?.message || "No se pudo completar el inicio de sesión con Microsoft.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-center items-center p-4 font-sans">
      <Card noPadding className="w-full max-w-md">
        <div className="p-8 flex flex-col items-center text-center gap-4">
          <span
            className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin"
            aria-hidden="true"
          />
          <p className="text-sm text-text-secondary">
            {processing ? "Verificando tu sesión de Microsoft…" : "Redirigiendo…"}
          </p>
        </div>
      </Card>
    </div>
  );
};
