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
