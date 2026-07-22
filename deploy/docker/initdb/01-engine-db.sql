-- Base de datos PROPIA del motor (hallazgo crítico del ensayo pre-piloto
-- 2026-07-22): el flujo de migración Prisma del motor, en el primer arranque,
-- aplica un diff DB-viva↔schema que DROPea como "drift" toda tabla ajena —
-- compartir base con el backend destruía el esquema del producto. Bases
-- separadas = aislamiento permanente (también ante upgrades del motor).
-- docker-entrypoint-initdb.d: corre SOLO en la inicialización del volumen.
CREATE DATABASE basa_engine OWNER CURRENT_USER;
