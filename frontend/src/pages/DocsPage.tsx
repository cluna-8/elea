import React, { useState } from "react";

type Section =
  | "overview"
  | "projects"
  | "dpas"
  | "dsr"
  | "retention"
  | "dpo"
  | "pipeline"
  | "checklist";

const sections: { id: Section; label: string }[] = [
  { id: "overview", label: "Visión general" },
  { id: "projects", label: "Proyectos de Compliance" },
  { id: "dpas", label: "Registro de DPAs" },
  { id: "dsr", label: "Derechos del Interesado" },
  { id: "retention", label: "Retención de Datos" },
  { id: "dpo", label: "Panel DPO" },
  { id: "pipeline", label: "Cómo funciona el pipeline" },
  { id: "checklist", label: "Checklist producción" },
];

const Badge: React.FC<{ color: "success" | "warning" | "danger" | "primary" | "slate"; children: React.ReactNode }> = ({ color, children }) => {
  const colors = {
    success: "bg-success/10 text-success border-success/20",
    warning: "bg-warning/10 text-warning border-warning/20",
    danger: "bg-danger/10 text-danger border-danger/20",
    primary: "bg-primary/10 text-primary border-primary/20",
    slate: "bg-slate-800 text-slate-400 border-slate-700",
  };
  return (
    <span className={`inline-block text-[10px] font-mono font-semibold px-2 py-0.5 rounded border ${colors[color]}`}>
      {children}
    </span>
  );
};

const Table: React.FC<{ headers: string[]; rows: (string | React.ReactNode)[][] }> = ({ headers, rows }) => (
  <div className="overflow-x-auto rounded-lg border border-slate-700/40 my-4">
    <table className="w-full text-xs text-left">
      <thead className="bg-background/60 border-b border-slate-700/40 text-text-secondary uppercase tracking-wider">
        <tr>{headers.map((h, i) => <th key={i} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr>
      </thead>
      <tbody className="divide-y divide-slate-700/20 text-white">
        {rows.map((row, i) => (
          <tr key={i} className="hover:bg-slate-800/20">
            {row.map((cell, j) => <td key={j} className="px-4 py-2.5 align-top">{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const Section: React.FC<{ title: string; subtitle?: string; children: React.ReactNode }> = ({ title, subtitle, children }) => (
  <div className="space-y-4">
    <div>
      <h2 className="text-xl font-bold text-white">{title}</h2>
      {subtitle && <p className="text-sm text-text-secondary mt-1">{subtitle}</p>}
    </div>
    {children}
  </div>
);

const Callout: React.FC<{ type: "info" | "warning" | "danger"; children: React.ReactNode }> = ({ type, children }) => {
  const styles = {
    info: "bg-primary/5 border-primary/20 text-primary",
    warning: "bg-warning/5 border-warning/20 text-warning",
    danger: "bg-danger/5 border-danger/20 text-danger",
  };
  const icons = { info: "ℹ", warning: "⚠", danger: "✖" };
  return (
    <div className={`border rounded-lg px-4 py-3 text-xs flex gap-3 my-3 ${styles[type]}`}>
      <span className="text-sm shrink-0">{icons[type]}</span>
      <div>{children}</div>
    </div>
  );
};

const H3: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <h3 className="text-sm font-bold text-white mt-6 mb-2">{children}</h3>
);

const P: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="text-xs text-text-secondary leading-relaxed">{children}</p>
);

const CheckItem: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <li className="flex gap-2 text-xs text-text-secondary items-start">
    <span className="text-slate-600 mt-0.5 shrink-0">☐</span>
    <span>{children}</span>
  </li>
);

export const DocsPage: React.FC = () => {
  const [active, setActive] = useState<Section>("overview");

  return (
    <div className="flex gap-0 h-full max-w-6xl mx-auto">
      {/* Sidebar */}
      <aside className="w-52 shrink-0 pr-6 pt-2 sticky top-0 self-start">
        <p className="text-[10px] uppercase tracking-widest text-text-secondary font-semibold mb-3">Documentación</p>
        <nav className="space-y-0.5">
          {sections.map(s => (
            <button key={s.id} onClick={() => setActive(s.id)}
              className={`w-full text-left px-3 py-2 rounded text-xs transition-all ${active === s.id ? "bg-primary/10 text-primary font-semibold" : "text-text-secondary hover:text-white hover:bg-slate-800/40"}`}>
              {s.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Content */}
      <main className="flex-1 space-y-8 pb-16 min-w-0">

        {/* ── Overview ──────────────────────────────────────────────────── */}
        {active === "overview" && (
          <Section title="Políticas de Cumplimiento" subtitle="GDPR · EU AI Act · ENS — Guía para administradores y DPO">
            <P>
              El módulo de compliance implementa los controles mínimos exigibles para operar un gateway de IA con datos sensibles (PII comercial / PHI) en la UE.
              Cada sección cubre un requisito legal distinto — configúralas en orden antes de pasar a producción.
            </P>

            <Table
              headers={["Marco legal", "Artículos clave", "Qué cubre este módulo"]}
              rows={[
                ["GDPR (UE 2016/679)", "Art. 5, 9, 12–22, 28, 35", "Base legal, DPAs, solicitudes de sujetos, retención, DPIA"],
                ["EU AI Act (UE 2024/1689)", "Art. 50", "Notificación obligatoria de uso de IA — en vigor agosto 2026"],
                ["ENS (RD 311/2022)", "Medidas de trazabilidad", "Retención mínima 365 días para eventos de seguridad"],
              ]}
            />

            <Callout type="warning">
              <strong>Este módulo no reemplaza la asesoría legal.</strong> Proporciona controles técnicos. El DPO del centro debe validar que la configuración refleja la DPIA aprobada y el Registro de Actividades de Tratamiento (RAT).
            </Callout>

            <H3>Orden de configuración recomendado</H3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[
                { n: "1", t: "Registrar DPAs", d: "Antes de enviar cualquier dato a un proveedor externo" },
                { n: "2", t: "Crear Proyecto de Compliance", d: "Define la base legal y activa las reglas del pipeline" },
                { n: "3", t: "Revisar Retención", d: "Ajusta los períodos según la DPIA del centro" },
                { n: "4", t: "Verificar Panel DPO", d: "Confirma que no hay alertas antes de ir a producción" },
              ].map(item => (
                <div key={item.n} className="bg-panel border border-slate-700/40 rounded-lg p-3 flex gap-3 items-start">
                  <span className="text-primary font-bold text-lg leading-none">{item.n}</span>
                  <div>
                    <p className="text-xs font-semibold text-white">{item.t}</p>
                    <p className="text-[10px] text-text-secondary mt-0.5">{item.d}</p>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* ── Projects ──────────────────────────────────────────────────── */}
        {active === "projects" && (
          <Section title="Proyectos de Compliance" subtitle="La unidad central de configuración — define qué reglas aplican a cada llamada al chat">
            <P>
              Un <strong className="text-white">Proyecto de Compliance</strong> agrupa las reglas que se aplican a todas las llamadas al chat mientras esté activo.
              Puedes tener múltiples proyectos para distintos contextos de uso (marketing, gastos, farmacovigilancia, investigación).
            </P>

            <H3>Bases legales disponibles</H3>
            <Table
              headers={["Opción", "Cuándo usarla"]}
              rows={[
                [<span className="text-white font-semibold">Art. 9(2)(h) — Prestación sanitaria / farmacovigilancia</span>, "Para datos de salud y farmacovigilancia/ensayos. Requiere supervisión humana cualificada."],
                [<span className="text-white font-semibold">Art. 9(2)(b) — Empleo / RRHH</span>, "Datos de empleados y representantes. Base habitual para gastos y RRHH."],
                ["Art. 9(2)(j) — Investigación / interés público", "Proyectos de investigación anonimizados. Requiere DPIA y medidas adicionales."],
                ["Art. 9(2)(a) — Consentimiento explícito", "Solo si tienes consentimiento firmado del interesado. No recomendado para uso rutinario."],
                ["Art. 6(1)(b) — Ejecución de contrato", "Procesos contractuales con clientes/proveedores (ej: gastos, campañas)."],
                ["Art. 6(1)(f) — Interés legítimo", "Marketing y analítica con balance de intereses documentado."],
                ["Art. 6(1)(c) — Obligación legal", "Para procesos obligatorios por ley."],
                ["Art. 6(1)(e) — Misión de interés público", "Para entidades públicas. No cubre datos de categoría especial por sí solo."],
              ]}
            />

            <H3>Niveles de riesgo EU AI Act</H3>
            <Table
              headers={["Nivel", "Descripción", "Obligaciones"]}
              rows={[
                [<Badge color="slate">Riesgo Mínimo</Badge>, "Chatbots informativos generales sin decisiones sobre personas", "Sin obligaciones adicionales"],
                [<Badge color="primary">Riesgo Limitado</Badge>, "Sistemas que interactúan con humanos", <><Badge color="primary">Art. 50</Badge> Notificación IA obligatoria desde ago. 2026</>],
                [<Badge color="warning">Alto Riesgo — Annex III</Badge>, "Farmacovigilancia automatizada, evaluación automatizada de personas, decisión regulatoria autónoma", "DPIA + EUDB + supervisión humana + logs 10 años"],
                [<Badge color="danger">Alto Riesgo — Annex I (MDR)</Badge>, "Producto sanitario con marcado CE", "Requisitos MDR + EU AI Act acumulados"],
              ]}
            />

            <Callout type="warning">
              Para farmacovigilancia o evaluación automatizada de personas (representantes/empleados), el nivel correcto es <strong>Alto Riesgo — Annex III</strong>. Esto activa la obligación de DPIA, notificación IA y revisión humana. Para marketing y gastos sin decisiones sobre personas, suele bastar Riesgo Limitado + Art. 50.
            </Callout>

            <H3>Qué hace cada opción del proyecto</H3>
            <Table
              headers={["Opción", "Qué activa en el pipeline"]}
              rows={[
                [<span className="text-white font-semibold">Forzar región EU</span>, "Bloquea la llamada con HTTP 503 si el modelo no pertenece a un proveedor con región EU (azure-*, bedrock-eu-*, vertex-eu-*, ollama-*)"],
                [<span className="text-white font-semibold">Notificación IA</span>, "Prepend del aviso legal antes de la primera respuesta de cada sesión (1 vez por hora por API key)"],
                [<span className="text-white font-semibold">Revisión humana</span>, "Genera un UUID de revisión por cada respuesta, visible en /compliance/review/pending para supervisión humana"],
                [<span className="text-white font-semibold">Referencia DPIA</span>, "Campo documental — aparece en el Panel DPO y activa alerta si está vacío en proyectos alto riesgo"],
              ]}
            />

            <H3>Configuración paso a paso — proyecto de farmacovigilancia</H3>
            <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-2 text-xs font-mono text-text-secondary">
              <p><span className="text-primary">1.</span> <span className="text-white">Nombre:</span> Farmacovigilancia [Producto]</p>
              <p><span className="text-primary">2.</span> <span className="text-white">Base legal:</span> Art. 9(2)(h)</p>
              <p><span className="text-primary">3.</span> <span className="text-white">Nivel de riesgo:</span> Alto Riesgo — Annex III</p>
              <p><span className="text-primary">4.</span> <span className="text-white">Notificación IA:</span> ✅ activada</p>
              <p><span className="text-primary">5.</span> <span className="text-white">Revisión humana:</span> ✅ activada</p>
              <p><span className="text-primary">6.</span> <span className="text-white">Forzar región EU:</span> ✅ si se procesan datos sensibles reales</p>
              <p><span className="text-primary">7.</span> <span className="text-white">Referencia DPIA:</span> completar cuando el DPO entregue el documento</p>
              <p><span className="text-primary">8.</span> <span className="text-white">Guardar → Activar el proyecto</span></p>
            </div>
          </Section>
        )}

        {/* ── DPAs ──────────────────────────────────────────────────────── */}
        {active === "dpas" && (
          <Section title="Registro de DPAs" subtitle="Art. 28 GDPR — Contratos obligatorios con proveedores de LLM">
            <Callout type="danger">
              <strong>Sin DPA firmado con el proveedor del LLM, no se pueden enviar datos sensibles.</strong> El incumplimiento del Art. 28 GDPR puede conllevar multas de hasta 10 M€ o el 2% de la facturación global.
            </Callout>

            <H3>Proveedores y su cobertura para datos sensibles</H3>
            <Table
              headers={["Proveedor", "Cubre Art. 9", "Región EU", "Recomendación"]}
              rows={[
                ["Azure OpenAI (Microsoft)", <Badge color="success">✅ Sí</Badge>, <Badge color="success">✅ sweden, france</Badge>, <span className="text-success font-semibold">Recomendado para PHI</span>],
                ["AWS Bedrock (Amazon)", <Badge color="success">✅ Sí (BAA)</Badge>, <Badge color="success">✅ eu-west-1, eu-central-1</Badge>, <span className="text-success font-semibold">Recomendado para PHI</span>],
                ["Google Vertex AI", <Badge color="success">✅ Sí</Badge>, <Badge color="success">✅ europe-west1</Badge>, "Válido con DPA firmado"],
                ["OpenAI directo", <Badge color="warning">⚠ Solo Enterprise</Badge>, <Badge color="danger">❌ No garantizado</Badge>, <span className="text-danger font-semibold">No recomendado para PHI</span>],
                ["Ollama (local)", <Badge color="success">✅ N/A — local</Badge>, <Badge color="success">✅ Siempre</Badge>, "Ideal para datos muy sensibles"],
              ]}
            />

            <H3>Estados del DPA y qué hacer</H3>
            <Table
              headers={["Estado", "Significado", "Acción requerida"]}
              rows={[
                [<Badge color="success">Activo</Badge>, "DPA vigente", "Ninguna"],
                [<Badge color="warning">Por vencer</Badge>, "Vence en menos de 30 días", "Renovar o negociar prórroga con el proveedor"],
                [<Badge color="danger">Expirado</Badge>, "Vencimiento pasado", "Detener uso del proveedor hasta renovar el contrato"],
              ]}
            />

            <H3>Qué registrar en el campo "Referencia del documento"</H3>
            <P>
              Usa la URL interna de tu sistema documental (SharePoint, Confluence, etc.) donde está almacenado el DPA firmado.
              Esto permite al auditor o al DPO acceder al contrato directamente desde el panel.
            </P>
          </Section>
        )}

        {/* ── DSR ───────────────────────────────────────────────────────── */}
        {active === "dsr" && (
          <Section title="Derechos del Interesado (DSR)" subtitle="Art. 12–22 GDPR — Plazo de respuesta: 30 días calendario">
            <H3>Tipos de solicitudes</H3>
            <Table
              headers={["Tipo", "Artículo", "Qué implica técnicamente"]}
              rows={[
                [<span className="text-white font-semibold">Acceso</span>, "Art. 15", "Exportar todos los registros del sujeto en el audit log"],
                ["Rectificación", "Art. 16", "Corregir datos incorrectos en metadatos del registro"],
                [<span className="text-white font-semibold">Supresión</span>, "Art. 17", "Anonimizar o eliminar registros del sujeto — ver retención"],
                ["Portabilidad", "Art. 20", "Exportar datos en formato estructurado (JSON/CSV)"],
                ["Limitación", "Art. 18", "Marcar registros para excluirlos de análisis"],
              ]}
            />

            <H3>Flujo de trabajo recomendado</H3>
            <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-2">
              {[
                ["1", "Recepción", "Correo, formulario o presencial — registrar en DSR tracker con identificador del sujeto"],
                ["2", "Búsqueda", "Usar el buscador de la pestaña DSR → buscar por subject_id en audit logs"],
                ["3", "Verificación", "Confirmar identidad del solicitante antes de ejecutar cualquier acción"],
                ["4", "Acción técnica", "Exportar / anonimizar / corregir los registros encontrados"],
                ["5", "Cierre", "Marcar DSR como Completada con notas del resultado"],
                ["6", "Notificación", "Informar al sujeto del resultado — antes de que venzan los 30 días"],
              ].map(([n, t, d]) => (
                <div key={n} className="flex gap-3 text-xs">
                  <span className="text-primary font-bold w-4 shrink-0">{n}</span>
                  <span className="text-white font-semibold w-24 shrink-0">{t}</span>
                  <span className="text-text-secondary">{d}</span>
                </div>
              ))}
            </div>

            <Callout type="info">
              El sistema almacena <strong>identificadores pseudonimizados</strong>, no nombres ni NIF. El mapeo identificador → persona real debe estar en un sistema separado bajo custodia del DPO, nunca en este gateway.
            </Callout>
          </Section>
        )}

        {/* ── Retention ─────────────────────────────────────────────────── */}
        {active === "retention" && (
          <Section title="Políticas de Retención" subtitle="Art. 5(1)(e) GDPR — Limitación del plazo de conservación">
            <P>
              Los datos personales no se conservarán más tiempo del necesario para los fines del tratamiento.
              Configura los períodos según la DPIA del centro y documenta la justificación de cada uno.
            </P>

            <H3>Tipos de registro y valores por defecto</H3>
            <Table
              headers={["Tipo", "Valor por defecto", "Mínimo recomendado", "Nota"]}
              rows={[
                ["Contenido de prompts y respuestas", "90 días", "30 días", "Reducir al mínimo posible para PHI real"],
                ["Metadatos de uso (tokens, coste, modelo)", "365 días", "90 días", "Necesario para auditoría de costes anuales"],
                [<span className="text-white font-semibold">Eventos de seguridad</span>, "365 días", <Badge color="warning">No reducir</Badge>, "Obligatorio ENS — detección de patrones de ataque"],
                [<span className="text-white font-semibold">Auditoría de configuración</span>, "730 días", <Badge color="warning">Mínimo 365 días</Badge>, "Trazabilidad de decisiones administrativas"],
              ]}
            />

            <Callout type="warning">
              La <strong>purga automática</strong> de registros vencidos está en el roadmap (feature 007). Por ahora la retención se configura pero la eliminación debe ejecutarse manualmente consultando el campo <code className="font-mono text-xs bg-slate-800 px-1 rounded">purge_log</code>.
            </Callout>

            <H3>Cómo documentar la justificación para la DPIA</H3>
            <P>
              El campo "Justificación" de cada tipo de log debe responder: <em className="text-white">¿Por qué necesitamos estos datos durante este período?</em>
            </P>
            <div className="bg-panel border border-slate-700/40 rounded-lg p-4 text-xs text-text-secondary font-mono">
              <p className="text-text-secondary mb-1">Ejemplo para metadatos de uso (365 días):</p>
              <p className="text-white italic">"Los metadatos de uso se conservan 365 días para auditoría interna de costes y para poder responder a reclamaciones de facturación durante el año fiscal en que se generaron. Período revisable anualmente por el DPO."</p>
            </div>
          </Section>
        )}

        {/* ── DPO Panel ─────────────────────────────────────────────────── */}
        {active === "dpo" && (
          <Section title="Panel DPO" subtitle="Vista consolidada del estado de cumplimiento para el Delegado de Protección de Datos">
            <H3>Indicadores y cómo interpretarlos</H3>
            <Table
              headers={["Indicador", "Verde ✅", "Amarillo ⚠", "Rojo ✖"]}
              rows={[
                ["Proyectos Activos", "≥1 activo, sin alertas", "Activos con alertas (sin DPIA)", "0 activos"],
                ["DPAs Vigentes", "Todos activos", "Alguno por vencer en <30 días", "Alguno expirado"],
                ["DPIAs Pendientes", "0 pendientes", "—", "≥1 proyecto alto riesgo sin DPIA"],
                ["DSRs Abiertas", "0 abiertas", "≥1 abierta (plazo en curso)", "≥1 abierta hace +25 días"],
                ["Enmascaramiento PHI", ">80%", "40–80%", "<40%"],
                ["Notificación IA (Art. 50)", ">90%", "50–90%", "<50% — obligatorio desde ago. 2026"],
                ["Revisión Humana", ">95% completadas", "80–95%", "<80%"],
              ]}
            />

            <H3>Revisión DPO recomendada (mensual)</H3>
            <ul className="space-y-2 mt-2">
              {[
                "Comprobar que no hay DPAs expirados — si los hay, detener uso del proveedor hasta renovación",
                "Verificar que todos los proyectos de alto riesgo tienen referencia DPIA completada",
                "Revisar DSRs abiertas — si alguna supera 25 días, escalar a responsable del tratamiento",
                "Revisar tasa de notificación IA — debe acercarse al 100% (obligatoria desde agosto 2026)",
                "Revisar revisiones humanas pendientes en la API /compliance/review/pending",
              ].map((item, i) => <CheckItem key={i}>{item}</CheckItem>)}
            </ul>
          </Section>
        )}

        {/* ── Pipeline ──────────────────────────────────────────────────── */}
        {active === "pipeline" && (
          <Section title="Cómo funciona el pipeline de chat" subtitle="Qué ocurre internamente en cada llamada al chat">
            <P>
              Cada vez que un usuario envía un mensaje, el sistema ejecuta este flujo. Los controles de compliance se aplican <strong className="text-white">antes y después</strong> de llamar al LLM.
            </P>

            <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-3 font-mono text-xs my-4">
              {[
                { step: "1", color: "text-slate-400", label: "Petición entrante", detail: "El cliente envía su mensaje con la API key" },
                { step: "2", color: "text-primary", label: "Autenticación API key", detail: "Verifica que la key existe y no ha superado su presupuesto" },
                { step: "3", color: "text-primary", label: "Guardianes de contenido", detail: "Presidio enmascara PII · LiteLLM moderation filtra contenido dañino" },
                { step: "4", color: "text-warning", label: "Compliance: región EU", detail: "Si eu_region_required=true y modelo no es azure-*/bedrock-eu-* → HTTP 503, la petición no llega al LLM" },
                { step: "5", color: "text-warning", label: "Compliance: disclosure", detail: "Si disclosure no entregado en última hora → prepara prefijo de notificación IA" },
                { step: "6", color: "text-warning", label: "Compliance: revisión humana", detail: "Si human_review_required=true → genera UUID de revisión" },
                { step: "7", color: "text-success", label: "Llamada al LLM", detail: "LiteLLM hace el routing al proveedor configurado" },
                { step: "8", color: "text-success", label: "Post-proceso", detail: "Prepend del disclosure si aplica · guarda review entry · escribe audit log" },
                { step: "9", color: "text-slate-400", label: "Respuesta al usuario", detail: "Con o sin prefijo de notificación según configuración" },
              ].map(item => (
                <div key={item.step} className="flex gap-3 items-start">
                  <span className={`font-bold w-4 shrink-0 ${item.color}`}>{item.step}</span>
                  <span className={`font-semibold w-44 shrink-0 ${item.color}`}>{item.label}</span>
                  <span className="text-text-secondary">{item.detail}</span>
                </div>
              ))}
            </div>

            <H3>Ejemplo de respuesta con notificación IA activa</H3>
            <div className="bg-panel border border-slate-700/40 rounded-lg p-4 text-xs font-mono space-y-2">
              <p className="text-primary">ℹ️ Este servicio utiliza inteligencia artificial para generar respuestas.</p>
              <p className="text-primary">Las respuestas pueden contener errores. Consulte siempre a un especialista</p>
              <p className="text-primary">antes de tomar decisiones de alto riesgo. (Art. 50 EU AI Act)</p>
              <p className="text-slate-600">─────────────────────────────────────</p>
              <p className="text-text-secondary">[Respuesta del LLM aquí]</p>
            </div>
            <p className="text-[10px] text-text-secondary mt-2">El aviso aparece una vez por hora por API key — no en cada mensaje, para no interrumpir conversaciones continuas.</p>

            <H3>Qué NO hacen las políticas de compliance</H3>
            <Table
              headers={["Capacidad", "Quién lo hace"]}
              rows={[
                ["Filtrar contenido dañino o inapropiado", "Guardianes de contenido (Seguridad → Guardianes)"],
                ["Bloquear usuarios individuales", "Políticas de presupuesto (Usuarios & Presupuestos)"],
                ["Limitar peticiones por minuto (rate limiting)", "Pendiente — Feature 006 con Redis"],
                ["Anonimización completa de datos", "Presidio enmascara en memoria pero no anonimiza en base de datos"],
              ]}
            />
          </Section>
        )}

        {/* ── Checklist ─────────────────────────────────────────────────── */}
        {active === "checklist" && (
          <Section title="Checklist antes de producción" subtitle="Verifica estos puntos antes de desplegar con datos reales de pacientes">
            <H3>Legal / Organizativo</H3>
            <ul className="space-y-2 mt-2">
              {[
                "DPIA completada y aprobada por el DPO para cada caso de uso de alto riesgo (Annex III)",
                "DPA firmado con cada proveedor de LLM que recibirá datos de pacientes — registrado en el panel",
                "Política de retención revisada y aprobada por el DPO — justificaciones documentadas",
                "Procedimiento de respuesta a DSR documentado: quién gestiona, en qué plazo, canal de comunicación",
                "Registro de Actividades de Tratamiento (RAT) actualizado con este sistema",
                "Notificación a la AEPD si el tratamiento requiere inscripción previa",
              ].map((item, i) => <CheckItem key={i}>{item}</CheckItem>)}
            </ul>

            <H3>Configuración técnica</H3>
            <ul className="space-y-2 mt-2">
              {[
                "Al menos 1 proyecto de compliance activo con base legal correcta para el caso de uso",
                "DPA del proveedor LLM registrado con 'Cubre Art. 9 = Sí'",
                "Notificación IA activada en el proyecto (obligatoria EU AI Act Art. 50 desde agosto 2026)",
                "Si se procesan datos clínicos reales: eu_region_required = true y modelo azure-* o bedrock-eu-*",
                "Presidio activado para enmascaramiento de PII (Seguridad → Guardianes → Presidio PII Masking)",
                "Retención de prompt_content configurada ≤90 días para PHI según DPIA",
              ].map((item, i) => <CheckItem key={i}>{item}</CheckItem>)}
            </ul>

            <H3>Verificación post-despliegue</H3>
            <ul className="space-y-2 mt-2">
              {[
                "Panel DPO muestra 0 DPAs expirados y 0 DPIAs pendientes",
                "Tasa de notificación IA > 0% tras primeras llamadas de prueba",
                "Audit log registra ai_disclosure_delivered = true en primera llamada por sesión",
                "DSR de prueba creada, buscada por subject_id y marcada como completada",
                "Llamada de prueba con modelo no-EU bloqueada si eu_region_required = true",
              ].map((item, i) => <CheckItem key={i}>{item}</CheckItem>)}
            </ul>

            <Callout type="info">
              <strong>Roadmap de compliance pendiente:</strong> purga automática de datos vencidos (Feature 007), perfiles de usuario por grupo con base legal diferenciada (Feature 006), rate limiting con Redis (Feature 006).
            </Callout>
          </Section>
        )}

      </main>
    </div>
  );
};

export default DocsPage;
