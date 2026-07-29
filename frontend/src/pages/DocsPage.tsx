import React from "react";
import { getBrand } from "../services/branding";

// La doc de producto YA NO vive en el bundle de la app (spec 022, FR-009): tiene su
// propio sitio estático (servicio `docs` del stack, air-gap-first, versionado, ES/EN).
// Esta página queda solo como puente navegable hacia ese sitio.
export const DocsPage: React.FC = () => {
  const brand = getBrand();
  // El sitio de docs se publica en su propio puerto (DOCS_PORT, default 8082): sus assets
  // usan rutas absolutas y no se sirven bajo un subpath del ingress. Si la marca trae una
  // URL absoluta (dominio propio con TLS) se respeta; si no, se arma con el host actual.
  const docsHref = /^https?:\/\//.test(brand.docsUrl)
    ? brand.docsUrl
    : `${window.location.protocol}//${window.location.hostname}:${brand.docsPort ?? 8082}/`;
  return (
    <div className="max-w-2xl mx-auto mt-16 text-center">
      <div className="rounded-card border border-border bg-surface shadow-card p-10">
        <div className="text-5xl mb-4">📚</div>
        <h1 className="text-2xl font-semibold mb-2">Documentación de producto</h1>
        <p className="text-text-secondary mb-6">
          La documentación de {brand.name} vive en su propio sitio, con búsqueda, versiones e
          idiomas. Funciona también sin salida a internet.
        </p>
        <a
          href={docsHref}
          target="_blank"
          rel="noreferrer"
          className="inline-block px-6 py-3 rounded-lg bg-primary/90 hover:bg-primary text-white font-medium transition-colors"
        >
          Abrir la documentación →
        </a>
        <p className="text-xs text-text-tertiary mt-6">
          Si el enlace no abre, su instalación todavía no publica el sitio de documentación.
          Pídaselo a quien opera la instalación.
        </p>
      </div>
    </div>
  );
};
