"""Entrega en desarrollo de la extensión (057 T021, research R6): `sentinel/docker/compose.dev.yml`,
`sentinel/docker/prepare-dev.sh` y `sentinel/extensions.env.example`.

Sin Docker: se lee el YAML del override y se corre el script de preparación contra un directorio
temporal. Lo que se fija: qué se monta, qué variables llegan, que nada se active solo y que el
ejemplo de entorno no traiga secretos ni la variable que Eleia no define.
"""
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCKER = ROOT / "sentinel" / "docker"
OVERRIDE = yaml.safe_load((DOCKER / "compose.dev.yml").read_text(encoding="utf-8"))
BASE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
EXAMPLE = (ROOT / "sentinel" / "extensions.env.example").read_text(encoding="utf-8")


def _env_dict(service):
    """`environment` de un servicio del override como dict (admite lista `K=V` o mapping)."""
    env = OVERRIDE["services"][service].get("environment", {})
    if isinstance(env, dict):
        return {k: str(v) for k, v in env.items()}
    return dict(item.split("=", 1) for item in env)


def _example_vars():
    """Variables ACTIVAS (no comentadas) del ejemplo."""
    out = {}
    for linea in EXAMPLE.splitlines():
        if linea.strip() and not linea.lstrip().startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ── el override: solo agrega, sobre los servicios que ya existen ───────────────────────────────────

def test_el_override_solo_toca_backend_y_motor_que_la_base_ya_define():
    assert set(OVERRIDE["services"]) == {"backend", "engine"}
    assert set(OVERRIDE["services"]) <= set(BASE["services"])
    assert set(OVERRIDE) <= {"services", "name"}                 # no redefine redes ni volúmenes de la base


def test_el_backend_ve_el_paquete_de_la_extension_y_lo_importa():
    svc = OVERRIDE["services"]["backend"]
    assert "./sentinel:/opt/sentinel-ext/sentinel" in svc["volumes"]
    assert _env_dict("backend")["PYTHONPATH"] == "/opt/sentinel-ext"
    # los volúmenes de la base (código del backend y litellm) siguen: el override los suma, no los pisa
    assert "./backend:/app" in BASE["services"]["backend"]["volumes"]


def test_el_motor_lleva_las_extensiones_y_el_config_fusionado_desde_el_directorio_generado():
    vols = OVERRIDE["services"]["engine"]["volumes"]
    # mismo destino que la base ⇒ el override los reemplaza (compose fusiona volúmenes por destino)
    assert "./sentinel/docker/.dev/config.yaml:/app/config.yaml" in vols
    assert "./sentinel/docker/.dev/extensions:/app/extensions" in vols
    base_vols = BASE["services"]["engine"]["volumes"]
    assert "./litellm/config.yaml:/app/config.yaml" in base_vols and "./litellm/extensions:/app/extensions" in base_vols
    # nada se monta DENTRO del directorio de extensiones de la base (Docker crearía archivos vacíos ahí)
    assert not any(v.split(":")[1].startswith("/app/extensions/") for v in vols)


def test_el_entorno_de_la_extension_llega_a_backend_y_motor_por_un_archivo_opcional():
    for nombre in ("backend", "engine"):
        env_file = OVERRIDE["services"][nombre]["env_file"]
        assert env_file == [{"path": "${SENTINEL_EXTENSIONS_ENV_FILE:-./sentinel/extensions.env}", "required": False}]


def test_el_override_no_activa_nada_ni_pisa_la_base_de_datos_del_motor():
    texto = (DOCKER / "compose.dev.yml").read_text(encoding="utf-8")
    for var in ("GATEWAY_PLUGINS", "PLUGIN_PACKAGES", "ALEMBIC_EXTRA_VERSION_LOCATIONS", "REDIRECT_INTERNAL_KEY"):
        assert not re.search(rf"^\s*-?\s*{var}\s*[:=]", texto, flags=re.M), f"{var}: la activa el archivo de entorno, no el override"
    # hasta que el spike D14 (T019) lo valide, el motor sigue creando/migrando su esquema como hoy
    for nombre in ("backend", "engine"):
        assert "DISABLE_SCHEMA_UPDATE" not in _env_dict(nombre)
    assert "REDIRECT_OPERATOR_TENANT" not in texto


def test_la_region_de_la_instalacion_en_dev_es_latam_ar_y_se_puede_pisar():
    for nombre in ("backend", "engine"):
        assert _env_dict(nombre)["SENTINEL_ENTITY_REGION"] == "${SENTINEL_ENTITY_REGION:-latam_ar}"


# ── el ejemplo de entorno ───────────────────────────────────────────────────────────────────────────

def test_el_ejemplo_activa_la_extension_con_las_costuras_de_la_base():
    v = _example_vars()
    assert v["GATEWAY_PLUGINS"] == "sentinel.redirect.plugin"
    assert v["PLUGIN_PACKAGES"] == "sentinel.redirect.api,sentinel.catalog.api"
    assert v["ALEMBIC_EXTRA_VERSION_LOCATIONS"] == "/opt/sentinel-ext/sentinel/migrations"
    assert v["SENTINEL_ENTITY_REGION"] == "latam_ar"
    # los seeds son los de deploy/redirect-seeds, vistos por el backend en la misma ruta que hornea la imagen -ext
    assert "./deploy/redirect-seeds:/opt/sentinel-ext/seeds:ro" in OVERRIDE["services"]["backend"]["volumes"]
    seeds = v["REDIRECT_SEED_FILES"].split(",")
    assert seeds
    for s in seeds:
        assert s.startswith("/opt/sentinel-ext/seeds/"), s
        assert (ROOT / "deploy" / "redirect-seeds" / s.rsplit("/", 1)[1]).exists(), s


def test_el_ejemplo_no_trae_secretos_ni_la_variable_que_eleia_no_define():
    v = _example_vars()
    assert "REDIRECT_OPERATOR_TENANT" not in EXAMPLE            # R30: Eleia no la define, ni comentada
    assert "CATALOG_DIRECT_ENABLED" not in v                    # apagada en Eleia (T090)
    assert "INTERNAL_ALLOWED_CIDRS" not in EXAMPLE              # la fija el compose base (R31)
    # la llave interna es un placeholder: quien lo copia la genera (≥ 32 caracteres), no queda una conocida
    assert v["REDIRECT_INTERNAL_KEY"] in ("", "<generar>") or v["REDIRECT_INTERNAL_KEY"].startswith("<")
    for k, val in v.items():
        assert not re.search(r"(sk-|AKIA|ghp_|eyJ)[A-Za-z0-9_-]{8,}", val), k


# ── el preparador del directorio generado ───────────────────────────────────────────────────────────

def test_prepare_dev_genera_extensiones_y_config_fusionado(tmp_path):
    out = tmp_path / ".dev"
    res = subprocess.run(["bash", str(DOCKER / "prepare-dev.sh")], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin:/usr/local/bin", "SENTINEL_DEV_DIR": str(out)})
    assert res.returncode == 0, res.stderr
    base = sorted(p.name for p in (ROOT / "litellm" / "extensions").glob("*.py"))
    redirect = sorted(p.name for p in (ROOT / "sentinel" / "engine").glob("redirect_*.py"))
    assert redirect, "la extensión trae sus archivos del motor"
    assert sorted(p.name for p in (out / "extensions").glob("*.py")) == sorted(base + redirect)
    for nombre in base + redirect:                               # copias idénticas, no versiones paralelas
        fuente = (ROOT / "litellm" / "extensions" / nombre)
        fuente = fuente if fuente.exists() else ROOT / "sentinel" / "engine" / nombre
        assert (out / "extensions" / nombre).read_bytes() == fuente.read_bytes(), nombre
    cfg = yaml.safe_load((out / "config.yaml").read_text(encoding="utf-8"))
    guards = [g["guardrail_name"] for g in cfg["guardrails"]]
    assert guards == ["sentinel-guardian", "redirect-guard"]      # el guard después del de la base (QA A3)
    nombres = [m["model_name"] for m in cfg["model_list"]]
    assert "azure-gpt-4o-mini" in nombres and any(n.startswith("rdx-") for n in nombres)
    assert nombres.index("azure-gpt-4o-mini") < min(i for i, n in enumerate(nombres) if n.startswith("rdx-"))
    # el config de la base no se toca
    assert "redirect-guard" not in (ROOT / "litellm" / "config.yaml").read_text(encoding="utf-8")


def test_prepare_dev_es_idempotente_y_no_arrastra_archivos_viejos(tmp_path):
    out = tmp_path / ".dev"
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "SENTINEL_DEV_DIR": str(out)}
    subprocess.run(["bash", str(DOCKER / "prepare-dev.sh")], check=True, capture_output=True, env=env)
    (out / "extensions" / "viejo.py").write_text("# sobrante de una versión anterior")
    primero = (out / "config.yaml").read_bytes()
    subprocess.run(["bash", str(DOCKER / "prepare-dev.sh")], check=True, capture_output=True, env=env)
    assert not (out / "extensions" / "viejo.py").exists()
    assert (out / "config.yaml").read_bytes() == primero          # sin duplicados: parte siempre del config de la base


# ── S13: la clave de los marcadores estables llega a backend y motor, sin valor de ejemplo (057 T072/T093) ─────

def test_la_clave_de_marcadores_estables_llega_al_backend_y_al_motor_sin_valor_por_defecto():
    for servicio in ("backend", "engine"):
        assert _env_dict(servicio)["MASKING_NONCE_KEY"] == "${MASKING_NONCE_KEY:-}", servicio


def test_el_ejemplo_de_entorno_declara_la_clave_con_el_marcador_de_generar_y_nunca_con_un_valor():
    valor = _example_vars()["MASKING_NONCE_KEY"]
    assert valor == "<generar>"


def test_la_clave_de_marcadores_no_esta_en_los_defaults_de_la_base():
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "MASKING_NONCE_KEY" not in str(base)
