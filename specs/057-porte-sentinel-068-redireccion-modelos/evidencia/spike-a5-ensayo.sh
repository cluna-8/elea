#!/usr/bin/env bash
# Ensayo QA A5 / research R5: DISABLE_SCHEMA_UPDATE=true sobre COPIAS de bases existentes (no toca las del stack).
set -u
U=$(docker exec elea057-db printenv POSTGRES_USER); PW=$(docker exec elea057-db printenv POSTGRES_PASSWORD)
BACK=$(docker exec elea057-db printenv POSTGRES_DB); ENG=sentinel_engine
SPK=${SPIKE053_DIR:?directorio spike053/ de la 068 con run_cases.py}
psql_() { docker exec elea057-db psql -U "$U" -d "$1" -Atc "$2"; }
copiar() { # origen destino
  psql_ postgres "drop database if exists $2" >/dev/null; psql_ postgres "create database $2" >/dev/null
  docker exec elea057-db sh -c "pg_dump -U $U $1 | psql -q -U $U -d $2" >/dev/null 2>&1; }
tablas() { psql_ "$1" "select count(*) from information_schema.tables where table_schema='public'"; }
lista()  { psql_ "$1" "select table_name from information_schema.tables where table_schema='public' order by 1" | md5sum | cut -c1-12; }
correr() { # nombre db var
  local nombre=$1 db=$2 var=$3
  docker run -d --rm --name a5-$nombre --network elea057_sentinel-network --entrypoint sh \
    -e DATABASE_URL="postgresql://$U:$PW@db:5432/$db" ${var:+-e DISABLE_SCHEMA_UPDATE=$var} -e OPENAI_API_KEY= \
    -v $SPK:/spike:ro ghcr.io/cluna-8/elea-guardian-engine:057-gate \
    -c 'mkdir -p /tmp/work && cp /spike/* /tmp/work/ && cd /tmp/work && exec litellm --config config.yaml --host 127.0.0.1 --port 18900' >/dev/null
  for i in $(seq 1 90); do
    docker exec a5-$nombre python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:18900/health/liveliness',timeout=2)" >/dev/null 2>&1 && break; sleep 2; done
  docker logs a5-$nombre 2>&1 | grep -iE "migrat|schema|prisma|drop|DISABLE" | sed -E 's/postgresql:\/\/[^ ]*//' | head -8 | cut -c1-200
  docker exec a5-$nombre python3 -c "import urllib.request;print('liveliness',urllib.request.urlopen('http://127.0.0.1:18900/health/liveliness',timeout=5).status)" 2>&1 | tail -1
  docker stop a5-$nombre >/dev/null 2>&1
}
for caso in "shared_sin_var:$BACK:" "shared_con_var:$BACK:true" "motor_con_var:$ENG:true"; do
  IFS=: read nombre origen var <<<"$caso"
  db=spike_a5_${nombre}; copiar "$origen" "$db"
  echo "== $nombre (copia de $origen) DISABLE_SCHEMA_UPDATE=${var:-<sin definir>}"
  echo "   antes : tablas=$(tablas $db) huella=$(lista $db) users=$(psql_ $db 'select count(*) from users' 2>/dev/null || echo n/a)"
  correr "$nombre" "$db" "$var"
  echo "   después: tablas=$(tablas $db) huella=$(lista $db) users=$(psql_ $db 'select count(*) from users' 2>/dev/null || echo n/a)"
  psql_ postgres "drop database if exists $db" >/dev/null
done
