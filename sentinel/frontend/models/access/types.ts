import type { EntryView } from "../../catalog/helpers";
import type { Lookups } from "../../redirect/helpers";
import type { Profile } from "../accessApi";
import type { AccessPerms } from "./helpers";

/** Lo que la pestaña le pasa a cada sub-sección. */
export interface AccessCtx {
  perms: AccessPerms;
  /** Todos los perfiles, archivados incluidos (cada sección filtra lo que necesita). */
  profiles: Profile[];
  lookups: Lookups;
  entries: Pick<EntryView, "id" | "public_id" | "name">[];
  reload: () => Promise<void>;
}
