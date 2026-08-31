// Branding como CONFIG en runtime (spec 020 US2, FR-006/FR-008 — never fork).
// Al arrancar, la SPA intenta leer /branding/brand.json (volumen montado por el
// deploy; en dev no existe y cae al default Sentinel-neutro SIN romper, FR-009).
// Una marca por instancia: se resuelve una vez, antes del primer render.

import defaultLogo from "../logo.png";

export interface Brand {
  name: string;
  tagline: string;
  logoUrl: string;
  supportContact: string;
  // URL del sitio de documentación de producto (spec 022): por instancia, via
  // brand.json del deploy. Default: /docs/ detrás del mismo ingress.
  docsUrl: string;
  docsPort?: number;
  colors?: { primary?: string; background?: string; panel?: string };
}

const DEFAULT_BRAND: Brand = {
  name: "Sentinel Secure AI Gateway",
  tagline: "Pasarela segura de IA sanitaria",
  logoUrl: defaultLogo,
  supportContact: "",
  docsUrl: "/docs/",
};

let brand: Brand = DEFAULT_BRAND;

export function getBrand(): Brand {
  return brand;
}

export async function loadBranding(): Promise<Brand> {
  try {
    const res = await fetch("/branding/brand.json", { cache: "no-store" });
    if (res.ok) {
      const pack = await res.json();
      brand = {
        ...DEFAULT_BRAND,
        ...pack,
        // El logo del pack vive en el mismo volumen montado.
        logoUrl: pack.logo ? `/branding/${pack.logo}` : DEFAULT_BRAND.logoUrl,
      };
    }
  } catch {
    // Sin pack → default Sentinel-neutro (fallback documentado, FR-009).
  }
  document.title = brand.name;
  applyBrandColors(brand.colors);
  return brand;
}

// FR-005 (spec 029): el tema claro Foundry es FIJO. De la marca aplicamos SOLO
// el acento (colors.primary) a --primary y derivamos --primary-hover/--primary-tint.
// IGNORAMOS colors.background/panel A PROPÓSITO: el brand-pack de Cámara los trae
// OSCUROS y volverían a oscurecer el chrome. Sin colors.primary (dev/fallback)
// no tocamos nada → quedan los defaults claros de index.css.
function applyBrandColors(colors?: Brand["colors"]): void {
  const primary = hexToRgbTriplet(colors?.primary);
  if (!primary) return;
  const root = document.documentElement;
  root.style.setProperty("--primary", primary);
  root.style.setProperty("--primary-hover", scaleTriplet(primary, 0.82));      // ~18% más oscuro
  root.style.setProperty("--primary-tint", tintTripletOnWhite(primary, 0.06)); // 6% sobre blanco
}

// Las vars de acento son tripletas RGB ("15 108 189") para que los modificadores
// de opacidad de tailwind funcionen; el pack escribe hex normal (#0f6cbd).
function hexToRgbTriplet(hex?: string): string | null {
  if (!hex) return null;
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

// Multiplica cada canal por `f` (hover más oscuro).
function scaleTriplet(triplet: string, f: number): string {
  return triplet
    .split(" ")
    .map((c) => Math.max(0, Math.min(255, Math.round(Number(c) * f))))
    .join(" ");
}

// Mezcla el color con blanco a `alpha` de opacidad (tint muy claro para selección).
function tintTripletOnWhite(triplet: string, alpha: number): string {
  return triplet
    .split(" ")
    .map((c) => Math.round(Number(c) * alpha + 255 * (1 - alpha)))
    .join(" ");
}
