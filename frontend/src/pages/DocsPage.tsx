import React from "react";
import { getBrand } from "../services/branding";

// La doc de producto YA NO vive en el bundle de la app (spec 022, FR-009): tiene su
// propio sitio estático (servicio `docs` del stack, air-gap-first, versionado, ES/EN).
// Esta página queda solo como puente navegable hacia ese sitio.
export const DocsPage: React.FC = () => {
  const brand = getBrand();
  return (
    <div className="max-w-2xl mx-auto mt-16 text-center">
      <div className="rounded-card border border-border bg-surface shadow-card p-10">
        <div className="text-5xl mb-4">📚</div>
        <h1 className="text-2xl font-semibold mb-2">Documentación de producto</h1>
        <p className="text-text-secondary mb-6">
          La documentación de {brand.name} — instalación, white-label, administración,
          integraciones, API y compliance — vive en su propio sitio, con búsqueda,
          versiones e idiomas. Funciona también sin salida a internet.
        </p>
        <a
          href={brand.docsUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-block px-6 py-3 rounded-lg bg-primary/90 hover:bg-primary text-white font-medium transition-colors"
        >
          Abrir la documentación →
        </a>
        <p className="text-xs text-text-tertiary mt-6">
          Si este enlace no resuelve, tu instalación aún no publica el servicio de
          documentación: pedile al operador que lo habilite (servicio <code>docs</code> del stack).
        </p>
      </div>
    </div>
  );
};
