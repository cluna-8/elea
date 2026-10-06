// Pestaña «Kits»: la configuración lista de cada herramienta para un alcance (FR-030). Sin
// credencial por defecto; si se pide, el backend emite una llave NUEVA del alcance y la audita.
import React, { useState } from "react";
import { Button, Card } from "../../../frontend/src/components/ui";
import { KIT_TOOLS, KIT_TOOL_LABELS, KitTool, ScopeType } from "./catalog";
import { Lookups, Permissions } from "./helpers";
import { RedirectApiError, us5Api } from "./api";
import { Kit, KitFile, scopeParam, us5ErrorMessage } from "./insights";
import { Notice, ScopePicker, SelectField } from "./ui";

function download(file: KitFile) {
  const url = URL.createObjectURL(new Blob([file.content], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = file.path.split("/").pop() || "kit.txt";
  a.click();
  URL.revokeObjectURL(url);
}

export const KitsTab: React.FC<{ perms: Permissions; lookups: Lookups }> = ({ perms, lookups }) => {
  const [tool, setTool] = useState<KitTool>("claude_code");
  const [scope, setScope] = useState<{ type: ScopeType; value: string }>({ type: "tenant", value: "" });
  const [withKey, setWithKey] = useState(false);
  const [kit, setKit] = useState<Kit | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const noKeyForScope = scope.type === "connection";

  const generate = async () => {
    if (scope.type !== "tenant" && !scope.value) { setErr("Elegí a quién aplica el kit."); return; }
    setBusy(true); setErr(null); setKit(null);
    try {
      setKit(await us5Api.kit(tool, scopeParam(scope.type, scope.value), withKey && !noKeyForScope));
    } catch (e) {
      const status = e instanceof RedirectApiError ? e.status : undefined;
      setErr(us5ErrorMessage(status, (e as Error).message, "No hay modelos publicados para esta herramienta en este alcance."));
    } finally {
      setBusy(false);
    }
  };

  if (!perms.canAdmin) {
    return <Notice tone="info">Los kits los genera quien administra la redirección.</Notice>;
  }

  return (
    <div>
      <Notice tone="info">
        El kit sale del catálogo publicado hoy: la dirección de esta pasarela, el modo de autenticación,
        los modelos del alcance y los ajustes que evitan fallas conocidas de cada herramienta. No lleva
        credenciales salvo que lo pidas.
      </Notice>
      <Card title="Generar un kit" className="mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <SelectField label="Herramienta" value={tool} onChange={v => { setTool(v as KitTool); setKit(null); }}
            options={KIT_TOOLS.map(t => ({ value: t, label: KIT_TOOL_LABELS[t] }))} />
        </div>
        <ScopePicker type={scope.type} value={scope.value} lookups={lookups}
          onChange={(type, value) => { setScope({ type, value }); setKit(null); }} />
        <label className="flex items-start gap-2 mt-4 text-sm">
          <input type="checkbox" checked={withKey && !noKeyForScope} disabled={noKeyForScope}
            onChange={e => setWithKey(e.target.checked)} className="mt-1" />
          <span>
            Incluir una llave nueva para este alcance
            <span className="block text-xs text-text-tertiary">
              {noKeyForScope
                ? "Una conexión ya tiene su llave: pedí el kit sin credencial."
                : "Se emite una conexión nueva limitada a estos modelos y queda registrada. La llave se muestra una sola vez."}
            </span>
          </span>
        </label>
        <div className="flex justify-end mt-4"><Button onClick={generate} disabled={busy}>{busy ? "Generando…" : "Generar kit"}</Button></div>
      </Card>
      {err && <Notice tone="error" onClose={() => setErr(null)}>{err}</Notice>}
      {kit && (
        <div>
          {kit.issued_key_id && (
            <Notice tone="ok">Se emitió una llave nueva y va dentro del kit. Copiala ahora: no se vuelve a mostrar.</Notice>
          )}
          <div className="text-sm text-text-secondary mb-3">
            Modelos: <b>{kit.models.join(", ")}</b>
            {kit.context_window ? <> · Ventana mínima de los destinos: <b>{kit.context_window.toLocaleString("es")}</b> tokens</> : null}
          </div>
          {kit.files.map(f => (
            <Card key={f.path} title={f.path} className="mb-4">
              {f.install_path && <p className="text-xs text-text-tertiary mb-2">Instalar en {f.install_path}</p>}
              <pre className="text-xs bg-surface-2 rounded-md p-3 overflow-x-auto whitespace-pre-wrap break-all">{f.content}</pre>
              <div className="flex justify-end gap-2 mt-3">
                <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(f.content)}>Copiar</Button>
                <Button variant="secondary" onClick={() => download(f)}>Descargar</Button>
              </div>
            </Card>
          ))}
          {kit.notes.map(n => <p key={n} className="text-xs text-text-tertiary mb-1">{n}</p>)}
        </div>
      )}
    </div>
  );
};
