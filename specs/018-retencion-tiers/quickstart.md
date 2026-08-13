# Quickstart — validar la 018 de punta a punta

Prerrequisitos: stack Docker Compose local (`docker compose -p <tuequipo> up`), suite backend verde en main.

## 1 · SC-001: la purga borra lo vencido y solo lo vencido

```bash
# Sembrar 200 días de datos sintéticos (script de test, incluye filas license intercaladas,
# blocked%, rejected%, config_change_*, tráfico normal y human_reviews con response_text viejo)
docker compose exec backend python -m tests.seeds.seed_retention_dataset --days 200

# Forzar una corrida fuera de ventana (flag de test) y verificar por SQL:
docker compose exec backend python -m src.services.retention.purger --run-now
```

Verificación (SQL puro, sin conocer implementación): cero filas vencidas de clases purgables; cero no vencidas afectadas; todas las `model='license'` intactas; `response_text` NULL en reviews > 90 d con la fila de review presente; `verify_chain` y export true-up en verde.

## 2 · SC-002: rastro reconstructible

`SELECT purge_log FROM retention_policies;` + filas `config_audit` de resumen — reconstruir qué se borró, cuándo y bajo qué política usando SOLO ese registro.

## 3 · SC-004: el mundo post-017

```bash
docker compose exec backend pytest tests/integration/test_purge_post017.py -v
```

La fixture dropea `tenant_isolation_bootstrap` y conecta con rol NOSUPERUSER; purga + emisor de cadena pasan.

## 4 · Tier: pisos y auditoría

```bash
# Con tier estricto activo, intentar bajar config_audit a 400 → 422 con detalle del piso (730)
curl -X PUT .../api/v1/compliance/retention -d '{"log_type":"config_audit","retention_days":400}'
# Cambiar tier → verificar fila de auditoría con valor anterior/nuevo
```

Invariante: con cualquier tier, un request que dispara la capa de piso AI-Act sigue siendo evaluado (test de regresión de la 027).

## 5 · SC-003: el examen no se entera (con La ITV)

Bajo el perfil de carga del gate 125 (instrumento 035), disparar purga concurrente con backlog real → los 4 SLOs de oro se mantienen. Este paso lo corre La ITV con su harness; el criterio y el disparador ya están en su contrato de gates.
