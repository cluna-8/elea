"""Separación de la base del motor de la base del Guardian: cableado + scripts, SIN Docker.

El migrador del motor aplica un diff «base viva → su schema» que DROPea toda tabla ajena
(reproducido: `specs/ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` §8.4). Compartir base es el
riesgo; separarla es la cura, y la cura solo vale si TODAS las piezas están cableadas:
base propia (`ENGINE_DB`) + quien la crea + las dos URL internas (identidad y auditoría
por HTTP, porque el motor ya no ve las tablas del backend) + el respaldo de las dos bases.

Por qué vive en `harness/` y no en `backend/tests/`: la suite del backend corre en un
contenedor cuyo contexto es `./backend`; la raíz del repo (los compose, `deploy/`) no
existe ahí. Mismo motivo que `test_compose_entity_region_wiring.py`.

Lo que NO prueba (queda para el ensayo con Docker, con la compuerta del owner): que Postgres
cree la base de verdad, que el motor arranque sobre ella y que `pg_dump` produzca un dump
restaurable. Acá se prueba el contrato de los scripts con un `psql`/`docker` de mentira que
registra cómo lo llamaron."""
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_DEV = _REPO / "docker-compose.yml"
_PROD = _REPO / "deploy" / "docker" / "compose.prod.yml"
_INITDB = _REPO / "deploy" / "docker" / "initdb"
_INIT_SH = _INITDB / "01-engine-db.sh"
_BACKUP_SH = _REPO / "deploy" / "release" / "backup.sh"
_ENV_EXAMPLE = _REPO / ".env.example"
# Valores canario de los tests (no son secretos): se busca que NO aparezcan en ningún lado.
_CANARIO_ARGV = "valor-canario-argv"
_CANARIO_MANIFEST = "valor-canario-manifest"


def _cargar(ruta: Path) -> dict:
    assert ruta.exists(), f"no encuentro {ruta}"
    return yaml.safe_load(ruta.read_text())


def _env_como_dict(environment) -> dict:
    """`environment` puede ser lista (`K=v`, dev) o dict (`K: v`, prod)."""
    if isinstance(environment, dict):
        return {k: str(v) for k, v in environment.items()}
    out = {}
    for item in environment or []:
        k, _, v = str(item).partition("=")
        out[k] = v
    return out


def _depends_on(servicio: dict) -> dict:
    dep = servicio.get("depends_on", {})
    if isinstance(dep, list):
        return {n: {} for n in dep}
    return dep


# ─────────────────────────────── compose de desarrollo ───────────────────────────────

class TestComposeDesarrollo:
    def test_el_motor_usa_su_propia_base(self):
        env = _env_como_dict(_cargar(_DEV)["services"]["engine"]["environment"])
        url = env["DATABASE_URL"]
        assert "${ENGINE_DB:-sentinel_engine}" in url, url
        # Jamás la base del backend: es la que el migrador del motor destruye.
        assert "POSTGRES_DB" not in url, url

    def test_el_motor_pregunta_identidad_y_audita_por_http(self):
        env = _env_como_dict(_cargar(_DEV)["services"]["engine"]["environment"])
        assert env["SENTINEL_IDENTITY_URL"] == "http://backend:8000/api/v1/internal/identity"
        assert env["SENTINEL_AUDIT_URL"] == "http://backend:8000/api/v1/internal/audit"

    def test_las_urls_internas_apuntan_a_rutas_que_el_backend_expone(self):
        # Si el backend renombra la ruta, el motor da 401 a todo byok en silencio.
        src = (_REPO / "backend" / "src" / "api" / "internal.py").read_text()
        assert '"/identity"' in src and '"/audit"' in src

    def test_servicio_de_un_solo_disparo_que_crea_la_base(self):
        servicios = _cargar(_DEV)["services"]
        init = servicios["db-engine-init"]
        assert init.get("restart") == "no", "un disparo: no debe reiniciarse"
        assert "ports" not in init
        assert _depends_on(init)["db"]["condition"] == "service_healthy"
        env = _env_como_dict(init["environment"])
        assert env["ENGINE_DB"] == "${ENGINE_DB:-sentinel_engine}"
        assert env["PGHOST"] == "db"
        # Sirve con un volumen EXISTENTE (donde initdb no corre) porque va por TCP a `db`.
        monta = " ".join(init["volumes"])
        assert "deploy/docker/initdb/01-engine-db.sh" in monta

    def test_el_motor_espera_a_que_la_base_exista(self):
        dep = _depends_on(_cargar(_DEV)["services"]["engine"])
        assert dep["db-engine-init"]["condition"] == "service_completed_successfully"

    def test_el_init_comparte_el_default_de_la_base_con_el_motor(self):
        servicios = _cargar(_DEV)["services"]
        env_init = _env_como_dict(servicios["db-engine-init"]["environment"])
        env_motor = _env_como_dict(servicios["engine"]["environment"])
        # El nombre que crea el init y el que lee el motor salen del MISMO `${ENGINE_DB:-…}`.
        assert env_init["ENGINE_DB"] in env_motor["DATABASE_URL"]

    def test_el_backend_sigue_en_su_base(self):
        env = _env_como_dict(_cargar(_DEV)["services"]["backend"]["environment"])
        assert env["POSTGRES_DB"] == "${POSTGRES_DB:-sentinel_gateway}"

    def test_el_backend_sigue_esperando_al_motor_sano(self):
        # Las llaves se crean por la API del motor; el orden no es de seguridad (ya no
        # comparten base) sino de funcionamiento.
        dep = _depends_on(_cargar(_DEV)["services"]["backend"])
        assert dep["engine"]["condition"] == "service_healthy"

    def test_el_init_no_fija_container_name(self):
        # `scripts/check_stack_prefix.sh` compara los container_name con una lista a mano;
        # un disparo no necesita nombre estable (nadie hace `docker exec` a él).
        assert "container_name" not in _cargar(_DEV)["services"]["db-engine-init"]


# ─────────────────────────────── compose de producción ───────────────────────────────

class TestComposeProduccion:
    def test_la_base_del_motor_se_nombra_igual_en_motor_y_en_db(self):
        servicios = _cargar(_PROD)["services"]
        env_db = _env_como_dict(servicios["db"]["environment"])
        env_motor = _env_como_dict(servicios["engine"]["environment"])
        assert env_db["ENGINE_DB"] == "${ENGINE_DB:-sentinel_engine}"
        assert "${ENGINE_DB:-sentinel_engine}" in env_motor["DATABASE_URL"]

    def test_db_monta_initdb_y_hay_un_sh_genérico(self):
        monta = " ".join(_cargar(_PROD)["services"]["db"]["volumes"])
        assert "./initdb:/docker-entrypoint-initdb.d" in monta
        assert _INIT_SH.exists()

    def test_ya_no_queda_el_sql_de_nombre_fijo(self):
        # Un `.sql` con el nombre fijo y el `.sh` genérico a la vez crearían dos bases.
        assert not (_INITDB / "01-engine-db.sql").exists()

    def test_el_motor_mantiene_las_dos_urls_internas(self):
        env = _env_como_dict(_cargar(_PROD)["services"]["engine"]["environment"])
        assert env["SENTINEL_IDENTITY_URL"].endswith("/api/v1/internal/identity")
        assert env["SENTINEL_AUDIT_URL"].endswith("/api/v1/internal/audit")


class TestEnvExample:
    def test_engine_db_documentada_con_default_generico(self):
        lineas = _ENV_EXAMPLE.read_text().splitlines()
        assert "ENGINE_DB=sentinel_engine" in lineas
        i = lineas.index("ENGINE_DB=sentinel_engine")
        # Comentario inmediatamente arriba: el generador de la doc lo usa como descripción.
        assert lineas[i - 1].startswith("#"), "ENGINE_DB sin descripción arriba"


# ───────────────────────────── script de creación de la base ─────────────────────────────

_PSQL_STUB = """#!/bin/sh
# psql de mentira: registra argumentos y el SQL de stdin; falla si pedimos PSQL_STUB_FAIL.
{
  echo "ARGS: $*"
  echo "ENV PGHOST=${PGHOST:-} PGUSER=${PGUSER:-} PGPASSWORD=${PGPASSWORD:-}"
  echo "--- STDIN"
  cat
  echo "--- FIN"
} >> "$PSQL_LOG"
[ -z "${PSQL_STUB_FAIL:-}" ] || exit 3
"""


@pytest.fixture
def stub_bin(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    p = d / "psql"
    p.write_text(_PSQL_STUB)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return d


def _correr_init(stub_bin, tmp_path, env_extra=None, via="exec"):
    log = tmp_path / "psql.log"
    env = {
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "PSQL_LOG": str(log),
        "POSTGRES_USER": "admin_x",
    }
    env.update(env_extra or {})
    if via == "exec":
        cmd = ["sh", str(_INIT_SH)]
    else:
        # El entrypoint de la imagen de Postgres SOURCEA los .sh no ejecutables, bajo
        # `set -e`, dentro de su propio shell: el script no puede matar ese shell con
        # un `exit` ni cambiar sus opciones.
        cmd = ["bash", "-c", f'set -eu; . "{_INIT_SH}"; echo SIGUE-VIVO']
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return r, (log.read_text() if log.exists() else "")


class TestInitScript:
    def test_existe_y_es_sh_posix(self):
        assert _INIT_SH.exists()
        assert "bash" not in _INIT_SH.read_text().splitlines()[0]

    def test_crea_la_base_nombrada_por_engine_db(self, stub_bin, tmp_path):
        r, log = _correr_init(stub_bin, tmp_path, {"ENGINE_DB": "mi_motor"})
        assert r.returncode == 0, r.stderr
        assert "db=mi_motor" in log
        assert "CREATE DATABASE %I" in log

    def test_default_generico_sin_engine_db(self, stub_bin, tmp_path):
        r, log = _correr_init(stub_bin, tmp_path)
        assert r.returncode == 0, r.stderr
        assert "db=sentinel_engine" in log

    def test_es_idempotente_por_construccion(self, stub_bin, tmp_path):
        # Sin Postgres no se puede ver «la 2.ª vez no hace nada»; lo que sí se fija es que
        # el SQL solo emite el CREATE si la base NO existe.
        _, log = _correr_init(stub_bin, tmp_path)
        assert "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db')" in log
        assert "\\gexec" in log

    def test_el_nombre_viaja_como_variable_no_interpolado_en_el_sql(self, stub_bin, tmp_path):
        # Un ENGINE_DB hostil no debe poder inyectar SQL: llega por `-v db=…` y se cita
        # con %I / :'db', nunca por concatenación en el texto del SQL.
        hostil = 'x"; DROP DATABASE postgres; --'
        r, log = _correr_init(stub_bin, tmp_path, {"ENGINE_DB": hostil})
        assert r.returncode == 0, r.stderr
        sql = log.split("--- STDIN", 1)[1]
        assert "DROP DATABASE postgres" not in sql
        assert f"db={hostil}" in log  # ... y sí llegó, como valor, en los argumentos

    def test_no_pone_owner_explicito(self, stub_bin, tmp_path):
        # `OWNER CURRENT_USER` NO es SQL válido (fix del ensayo 2026-07-27): omitirlo deja
        # de dueño al rol que ejecuta, que es lo que se busca.
        _, log = _correr_init(stub_bin, tmp_path)
        assert "OWNER" not in log.split("--- STDIN", 1)[1]

    def test_conecta_a_postgres_con_on_error_stop(self, stub_bin, tmp_path):
        _, log = _correr_init(stub_bin, tmp_path)
        args = log.splitlines()[0]
        assert "ON_ERROR_STOP=1" in args
        assert "--dbname postgres" in args or "-d postgres" in args
        assert "admin_x" in args

    def test_usa_postgres_user_o_pguser(self, stub_bin, tmp_path):
        r, log = _correr_init(stub_bin, tmp_path, {"POSTGRES_USER": "", "PGUSER": "otro"})
        assert r.returncode == 0, r.stderr
        assert "otro" in log.splitlines()[0]

    def test_error_de_psql_se_propaga_y_no_se_traga(self, stub_bin, tmp_path):
        r, _ = _correr_init(stub_bin, tmp_path, {"PSQL_STUB_FAIL": "1"})
        assert r.returncode != 0

    def test_error_de_psql_aborta_tambien_cuando_se_sourcea(self, stub_bin, tmp_path):
        r, _ = _correr_init(stub_bin, tmp_path, {"PSQL_STUB_FAIL": "1"}, via="source")
        assert r.returncode != 0
        assert "SIGUE-VIVO" not in r.stdout

    def test_sourceado_no_mata_el_shell_del_entrypoint(self, stub_bin, tmp_path):
        r, _ = _correr_init(stub_bin, tmp_path, via="source")
        assert r.returncode == 0, r.stderr
        assert "SIGUE-VIVO" in r.stdout

    def test_sin_usuario_falla_ruidoso(self, stub_bin, tmp_path):
        r, _ = _correr_init(stub_bin, tmp_path, {"POSTGRES_USER": "", "PGUSER": ""})
        assert r.returncode != 0
        assert "POSTGRES_USER" in r.stderr

    def test_ejecuta_psql_sin_exponer_el_password_en_argumentos(self, stub_bin, tmp_path):
        r, log = _correr_init(stub_bin, tmp_path, dict(PGPASSWORD=_CANARIO_ARGV))
        assert r.returncode == 0, r.stderr
        assert _CANARIO_ARGV not in log.splitlines()[0]  # ARGS (visibles en `ps`)


# ───────────────────────────────── script de respaldo ─────────────────────────────────

_DOCKER_STUB = r"""#!/bin/sh
# docker de mentira para backup.sh. Registra cada invocación y emula lo mínimo:
#   exec ... psql ...         → «1» (la base existe) salvo DOCKER_STUB_NO_ENGINE_DB
#   exec ... pg_dump ... -d X → bytes falsos que nombran la base (para saber qué se volcó)
#   exec ... pg_restore -l    → lista falsa (lectura del dump por stdin)
echo "docker $*" >> "$DOCKER_LOG"
case "$*" in
  *pg_dump*)
    [ -z "${DOCKER_STUB_FAIL_DUMP:-}" ] || { echo "pg_dump: error simulado" >&2; exit 4; }
    base=$(echo "$*" | sed -E 's/.*(--dbname|-d)[ =]([^ ]+).*/\2/')
    echo "DUMP-DE:$base"
    ;;
  *pg_restore*) cat >/dev/null; echo "; Archive created at fake" ;;
  *psql*)
    case "$*" in
      *"$ENGINE_DB_EXPECTED"*) [ -z "${DOCKER_STUB_NO_ENGINE_DB:-}" ] && echo 1 || echo 0 ;;
      *) echo 1 ;;
    esac
    ;;
esac
exit 0
"""


@pytest.fixture
def docker_stub(tmp_path):
    d = tmp_path / "dbin"
    d.mkdir()
    p = d / "docker"
    p.write_text(_DOCKER_STUB)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return d


def _correr_backup(docker_stub, tmp_path, args=(), env_extra=None):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    log = tmp_path / "docker.log"
    env = {
        "PATH": f"{docker_stub}:{os.environ['PATH']}",
        "DOCKER_LOG": str(log),
        "POSTGRES_USER": "admin_x",
        "POSTGRES_DB": "gw_db",
        "ENGINE_DB": "motor_db",
        "ENGINE_DB_EXPECTED": "motor_db",
        "DB_CONTAINER": "mi-db",
        "HOME": str(tmp_path),
    }
    env.update(env_extra or {})
    r = subprocess.run(["bash", str(_BACKUP_SH), "-o", str(out), *args],
                       env=env, capture_output=True, text=True, cwd=tmp_path)
    return r, out, (log.read_text() if log.exists() else "")


class TestBackup:
    def test_existe_y_es_ejecutable(self):
        assert _BACKUP_SH.exists()
        assert os.access(_BACKUP_SH, os.X_OK)

    def test_una_sola_copia_con_las_dos_bases(self, docker_stub, tmp_path):
        r, out, log = _correr_backup(docker_stub, tmp_path)
        assert r.returncode == 0, r.stderr
        copias = list(out.iterdir())
        assert len(copias) == 1, copias
        with tarfile.open(copias[0]) as t:
            nombres = sorted(t.getnames())
            assert nombres == ["MANIFEST", "engine.dump", "gateway.dump"], nombres
            assert b"DUMP-DE:gw_db" in t.extractfile("gateway.dump").read()
            assert b"DUMP-DE:motor_db" in t.extractfile("engine.dump").read()
            manifest = t.extractfile("MANIFEST").read().decode()
        assert "gateway_db=gw_db" in manifest and "engine_db=motor_db" in manifest
        assert "sha256" in manifest

    def test_vuelca_primero_el_backend_y_despues_el_motor(self, docker_stub, tmp_path):
        # Una llave creada ENTRE los dos volcados: si el motor va después, la llave existe
        # en el motor y como mucho sobra (inocuo). Al revés, el backend apuntaría a una
        # llave que el motor no tiene.
        r, _, log = _correr_backup(docker_stub, tmp_path)
        assert r.returncode == 0, r.stderr
        dumps = [ln for ln in log.splitlines() if "pg_dump" in ln]
        assert len(dumps) == 2
        assert "gw_db" in dumps[0] and "motor_db" in dumps[1]

    def test_formato_custom_para_poder_restaurar_con_pg_restore(self, docker_stub, tmp_path):
        _, _, log = _correr_backup(docker_stub, tmp_path)
        for ln in (l for l in log.splitlines() if "pg_dump" in l):
            assert "-Fc" in ln

    def test_verifica_que_cada_dump_se_pueda_leer(self, docker_stub, tmp_path):
        _, _, log = _correr_backup(docker_stub, tmp_path)
        assert sum("pg_restore" in l and "-l" in l for l in log.splitlines()) == 2

    def test_si_falla_un_volcado_no_queda_ninguna_copia_a_medias(self, docker_stub, tmp_path):
        r, out, _ = _correr_backup(docker_stub, tmp_path, env_extra={"DOCKER_STUB_FAIL_DUMP": "1"})
        assert r.returncode != 0
        assert list(out.iterdir()) == []

    def test_si_no_existe_la_base_del_motor_falla_con_mensaje_claro(self, docker_stub, tmp_path):
        r, out, _ = _correr_backup(docker_stub, tmp_path, env_extra={"DOCKER_STUB_NO_ENGINE_DB": "1"})
        assert r.returncode != 0
        assert "motor_db" in r.stderr
        assert list(out.iterdir()) == []

    def test_default_de_la_base_del_motor_es_el_generico(self, docker_stub, tmp_path):
        env = {"ENGINE_DB": "", "ENGINE_DB_EXPECTED": "sentinel_engine"}
        r, out, log = _correr_backup(docker_stub, tmp_path, env_extra=env)
        assert r.returncode == 0, r.stderr
        assert "sentinel_engine" in log

    def test_contenedor_por_defecto_sigue_el_stack_prefix(self, docker_stub, tmp_path):
        r, _, log = _correr_backup(docker_stub, tmp_path,
                                   env_extra={"DB_CONTAINER": "", "STACK_PREFIX": "foo"})
        assert r.returncode == 0, r.stderr
        assert "exec -i foo-db" in log

    def test_lee_las_variables_de_un_env_file_sin_ejecutarlo(self, docker_stub, tmp_path):
        envf = tmp_path / "x.env"
        marca = tmp_path / "PWNED"
        envf.write_text(
            f"POSTGRES_DB=otra_gw\nENGINE_DB=otro_motor\nPOSTGRES_USER=u2\n$(touch {marca})\n"
            f"X=`touch {marca}`\n")
        r, _, log = _correr_backup(
            docker_stub, tmp_path, args=["--env-file", str(envf)],
            env_extra={"POSTGRES_DB": "", "ENGINE_DB": "", "POSTGRES_USER": "",
                       "ENGINE_DB_EXPECTED": "otro_motor"})
        assert r.returncode == 0, r.stderr
        assert not marca.exists(), "el env-file se EJECUTÓ"
        assert "otra_gw" in log and "otro_motor" in log

    def test_el_manifest_no_contiene_secretos(self, docker_stub, tmp_path):
        r, out, _ = _correr_backup(docker_stub, tmp_path,
                                   env_extra=dict(POSTGRES_PASSWORD=_CANARIO_MANIFEST))
        assert r.returncode == 0, r.stderr
        with tarfile.open(next(out.iterdir())) as t:
            assert _CANARIO_MANIFEST.encode() not in t.extractfile("MANIFEST").read()
        assert _CANARIO_MANIFEST not in r.stdout + r.stderr

    def test_la_copia_no_es_legible_por_otros_usuarios(self, docker_stub, tmp_path):
        # Contiene identidad y auditoría: 0600.
        _, out, _ = _correr_backup(docker_stub, tmp_path)
        modo = stat.S_IMODE(next(out.iterdir()).stat().st_mode)
        assert modo == 0o600, oct(modo)
