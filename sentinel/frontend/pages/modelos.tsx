// Página de plugin de la consola (costura S3, `@plugin-pages`): la pantalla única «Modelos» ocupa el
// lugar del ítem base `models` (`replaces`) y absorbe el catálogo y la redirección como pestañas.
// Roles legacy de la sesión: `admin` cubre tenant_admin y super_admin; cumplimiento y lectura
// consultan (cumplimiento además completa fichas). En este directorio va SOLO el módulo de entrada:
// el registry importa todo `*.ts(x)` de acá.
import { ModelsScreen } from "../models/ModelsScreen";
import { ModelsIcon } from "../models/icon";

export default {
  path: "/modelos",
  Component: ModelsScreen,
  menu: { label: "Modelos", section: "playground", icon: ModelsIcon },
  roles: ["admin", "compliance_officer", "lectura"],
  replaces: "models",
};
