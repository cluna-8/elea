// Branding como CONFIG en runtime (spec 020 US2, FR-006/FR-008 — never fork).
// Al arrancar, la SPA intenta leer /branding/brand.json (volumen montado por el
// deploy; en dev no existe y cae al default Basa-neutro SIN romper, FR-009).
// Una marca por instancia: se resuelve una vez, antes del primer render.

import defaultLogo from "../logo.png";

export interface Brand {
  name: string;
  tagline: string;
  logoUrl: string;
  supportContact: string;
  colors?: { primary?: string; background?: string; panel?: string };
}

const DEFAULT_BRAND: Brand = {
  name: "Basa Secure AI Gateway",
  tagline: "Pasarela segura de IA sanitaria",
  logoUrl: defaultLogo,
  supportContact: "",
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
    // Sin pack → default Basa-neutro (fallback documentado, FR-009).
  }
  document.title = brand.name;
  const root = document.documentElement;
  for (const [key, value] of Object.entries(brand.colors ?? {})) {
    const rgb = hexToRgbTriplet(value);
    if (rgb) root.style.setProperty(`--brand-${key}`, rgb);
  }
  return brand;
}

// Las vars de marca son tripletas RGB ("0 180 216") para que los modificadores
// de opacidad de tailwind funcionen; el pack escribe hex normal (#00b4d8).
function hexToRgbTriplet(hex?: string): string | null {
  if (!hex) return null;
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}
