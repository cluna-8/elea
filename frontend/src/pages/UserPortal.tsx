import React, { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { SessionUser } from "../services/auth";
import { getBrand } from "../services/branding";
import { Markdown } from "../components/Markdown";
import { CambiarMiPasswordModal } from "../components/CambiarMiPasswordModal";
import { Button, StatusBadge, cn, inputBaseClass } from "../components/ui";

// Portal exclusivo para el usuario final (rol client): chat limpio, selector de
// modelo y transparencia por respuesta (modelo usado, costo, datos protegidos).
// Sin acceso a la consola de administración — el gate vive en App.tsx.
//
// Portado del predecesor con dos adaptaciones de contrato:
// 1. El modo "Automático" volvió (spec 030): GET /chat/models antepone el pseudo-modelo
//    «auto» cuando el ruteo está activo, así que llega en la lista como un modelo más y
//    queda seleccionado por ser el primero. Acá NO hay lógica de ruteo: sólo la etiqueta
//    y, en la respuesta, el modelo que contestó.
// 2. El backend NO devuelve `blocked: true` en un 200 — un bloqueo por política
//    llega como HTTP 400/503 con `detail` en español (api.sendChatMessage lo
//    lanza como Error). Se muestra como aviso de la plataforma, no como fallo.

// El pseudo-modelo del ruteo automático. El `value` que viaja al backend es siempre el
// literal "auto"; lo que se traduce es sólo la etiqueta que ve el usuario final.
const AUTO_MODEL = "auto";
const etiquetaModelo = (nombre: string) =>
  nombre === AUTO_MODEL ? "Auto (ruteo inteligente)" : nombre;

interface Msg {
  role: "user" | "assistant" | "notice";
  text: string;
  modelUsed?: string;
  costUsd?: number;
  maskedCount?: number;
  /** La petición pasó por el ruteo automático. Este portal es el del usuario final: se
   *  dice QUÉ modelo terminó contestando y nada más — la ruta ganadora, el score y el
   *  motivo de degradación son del Debugger y de «Conexiones en vivo», no de acá. */
  viaAuto?: boolean;
}

interface PortalProps {
  user: SessionUser;
  onLogout: () => void;
}

export const UserPortal: React.FC<PortalProps> = ({ user, onLogout }) => {
  const [models, setModels] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [cambiarPassword, setCambiarPassword] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const brand = getBrand();

  useEffect(() => {
    api.getModels()
      .then((ms) => {
        const names = ms.filter((m: any) => m.is_configured).map((m: any) => m.model_name as string);
        setModels(names);
        if (names.length > 0) setSelected((prev) => prev || names[0]);
      })
      .catch(() => setModels([]));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || sending || !selected) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text }]);
    setSending(true);
    try {
      // Sesión del usuario logueado: sin llave virtual ni overrides de política.
      const res = await api.sendChatMessage(text, selected);
      const llm = res.pipeline_metadata?.layer_llm;
      const masking = res.pipeline_metadata?.layer_masking;
      setMessages((prev) => [...prev, {
        role: "assistant",
        text: res.response,
        modelUsed: llm?.model_used,
        costUsd: typeof llm?.cost_usd === "number" ? llm.cost_usd : undefined,
        maskedCount: masking?.active && Array.isArray(masking?.entities_detected)
          ? masking.entities_detected.length
          : undefined,
        // Presente sólo si la petición pasó por el router (contrato §POST /completions:
        // el campo está AUSENTE, no en null, cuando el modelo se eligió a mano).
        viaAuto: !!llm?.auto_router,
      }]);
    } catch (err: any) {
      // El `detail` del backend viene en español y ES el mensaje a mostrar: un
      // bloqueo por política de seguridad es una protección funcionando, no un
      // error del producto — por eso se pinta como aviso y no como fallo.
      setMessages((prev) => [...prev, {
        role: "notice",
        text: err?.message || "No se pudo procesar la consulta. Intente nuevamente.",
      }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="h-screen flex flex-col bg-canvas font-sans">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface shrink-0">
        <div className="flex items-center gap-4 min-w-0">
          <img src={brand.logoUrl} alt={brand.name} className="h-8 w-auto object-contain shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-text-primary leading-none truncate">Asistente Seguro</p>
            <p className="text-[11px] text-text-secondary mt-0.5 truncate">
              Sus consultas se procesan con protección de datos activa
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-text-secondary hidden sm:inline">{user.username}</span>
          <Button variant="ghost" size="sm" onClick={() => setCambiarPassword(true)}>
            Cambiar contraseña
          </Button>
          <Button variant="secondary" size="sm" onClick={onLogout}>
            Salir
          </Button>
        </div>
      </header>

      {/* Selector de modelo */}
      <div className="px-6 py-2.5 border-b border-border bg-surface flex items-center gap-2 flex-wrap shrink-0">
        <span className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold mr-1">Modelo:</span>
        {models.length === 0 && (
          <span className="text-[11px] text-text-tertiary">
            No hay modelos disponibles. Contacte a su administrador.
          </span>
        )}
        {models.map((m) => (
          <button
            key={m}
            onClick={() => setSelected(m)}
            className={cn(
              "px-3 py-1 rounded-full text-[11px] font-mono border transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              selected === m
                ? "bg-primary-tint text-primary border-primary/40 font-semibold"
                : "text-text-secondary border-border hover:text-text-primary hover:bg-surface-2"
            )}
          >
            {etiquetaModelo(m)}
          </button>
        ))}
      </div>

      {/* Mensajes */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center space-y-3">
            <StatusBadge tone="ok" dot>Canal Seguro Activo</StatusBadge>
            <p className="text-lg font-semibold text-text-primary">¿En qué puedo ayudar hoy?</p>
            <p className="text-xs text-text-secondary max-w-md">
              Sus datos personales se enmascaran antes de salir de la plataforma y cada
              respuesta indica el modelo utilizado y su costo.
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            {m.role === "notice" ? (
              <div className="max-w-[78%] rounded-card px-4 py-3 text-xs bg-warn-bg text-warn border border-warn/20">
                <p className="font-semibold mb-0.5">Solicitud no procesada</p>
                <p className="whitespace-pre-wrap">{m.text}</p>
              </div>
            ) : (
              <div
                className={cn(
                  "max-w-[78%] rounded-card px-4 py-3 text-sm",
                  m.role === "user"
                    ? "bg-primary text-white rounded-br-sm whitespace-pre-wrap"
                    : "bg-surface border border-border text-text-primary rounded-bl-sm shadow-card"
                )}
              >
                {m.role === "assistant" ? <Markdown>{m.text}</Markdown> : m.text}
                {m.role === "assistant" && (m.modelUsed || typeof m.costUsd === "number") && (
                  <div className="flex flex-wrap items-center gap-1.5 mt-2.5 pt-2 border-t border-border">
                    {/* Siempre el modelo REAL que contestó: si el proveedor estaba caído,
                        la petición la sirvió el modelo de reserva y el badge tiene que
                        decir quién respondió de verdad, no lo que se pidió. Con ruteo
                        automático se antepone «Auto →» para que el usuario entienda que él
                        no eligió ese modelo. */}
                    {m.modelUsed && (
                      <span
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-border text-text-secondary"
                        title={m.viaAuto ? "Modelo elegido automáticamente para esta consulta." : undefined}
                      >
                        {m.viaAuto ? `Auto → ${m.modelUsed}` : m.modelUsed}
                      </span>
                    )}
                    {typeof m.costUsd === "number" && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-border text-text-secondary">
                        ${m.costUsd.toFixed(6)}
                      </span>
                    )}
                    {typeof m.maskedCount === "number" && m.maskedCount > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-ok-bg text-ok font-medium">
                        {m.maskedCount === 1
                          ? "1 dato personal protegido"
                          : `${m.maskedCount} datos personales protegidos`}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-surface border border-border rounded-card rounded-bl-sm px-4 py-3 text-sm text-text-secondary flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-ping" />
              Procesando de forma segura…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-border bg-surface shrink-0">
        <form onSubmit={send} className="flex gap-3 max-w-3xl mx-auto">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Escriba su consulta…"
            className={cn(inputBaseClass, "flex-1 h-11 border-border")}
          />
          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={sending || !input.trim() || !selected}
          >
            Enviar
          </Button>
        </form>
        <p className="text-center text-[10px] text-text-tertiary mt-2">
          Respuestas generadas por IA. Verifique la información importante antes de usarla.
        </p>
      </div>

      {cambiarPassword && <CambiarMiPasswordModal onClose={() => setCambiarPassword(false)} />}
    </div>
  );
};
export default UserPortal;
