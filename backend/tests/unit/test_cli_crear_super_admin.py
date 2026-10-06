"""`python -m src.cli crear-super-admin` / `resetear-super-admin`: el `super_admin` por comando.

`POST /users` ya no deja a un `tenant_admin` crear `super_admin` ni `compliance_officer`
(`auth.rbac.exigir_super_admin_para_rol`), y `super_admin` no lo autogenera ninguna
migración: la instalación necesita UNA vía para tener el primero. Este comando es esa vía:
idempotente, genérica (no sabe si la instalación es on-prem o cloud) y que sólo actúa si se
la invoca.

Unit tests sin Postgres: la `Session` es un doble y el contrato que se mide es el de la
fila que se inserta, el evento de auditoría y lo que sale por stdout. El camino completo
contra Postgres lo cubre `tests/integration/test_alta_primer_super_admin.py`.
"""
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from src import cli
from src.auth.passwords import MIN_PASSWORD_LEN, validar_password, verify_password
from src.models.tenant import DEFAULT_TENANT_ID
from src.models.user import User
from src.services import auth_events

USUARIO = "owner"
EMAIL = "owner@example.com"


class _DB:
    """`Session` doble: `existentes` es lo que ya hay en `users` (lista de `User`)."""

    def __init__(self, existentes=()):
        self.existentes = list(existentes)
        self.agregados = []
        self.commits = 0
        self.rollbacks = 0
        self.fallar_commit = None

    # Las consultas del comando se resuelven por los helpers del módulo (parcheados en los
    # tests que lo necesitan); estas dos cubren el camino por defecto.
    def add(self, obj):
        self.agregados.append(obj)

    def flush(self):
        pass

    def commit(self):
        if self.fallar_commit:
            raise self.fallar_commit
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def evento(monkeypatch):
    emit = MagicMock()
    monkeypatch.setattr(cli, "emit_auth_event", emit)
    return emit


def _password_de(out):
    """La línea `PASSWORD=<valor>` de stdout (contrato con el instalador)."""
    lineas = [l for l in out.splitlines() if l.startswith("PASSWORD=")]
    assert len(lineas) == 1, out
    return lineas[0].split("=", 1)[1]


def _existente(role="client", username="otro", email="otro@example.com"):
    return User(id=uuid.uuid4(), username=username, email=email, password_hash="x", role=role)


@pytest.fixture
def ocupacion(monkeypatch):
    """Controla las dos lecturas del comando sin Postgres."""
    estado = {"hay_super_admin": False, "ocupado": None}
    monkeypatch.setattr(cli, "_hay_super_admin", lambda db: estado["hay_super_admin"])
    monkeypatch.setattr(cli, "_campo_ocupado", lambda db, usuario, email: estado["ocupado"])
    return estado


# ── Creación ────────────────────────────────────────────────────────────────────────


def test_crea_el_super_admin_con_los_campos_del_contrato(ocupacion, evento):
    db = _DB()

    password = cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL)

    assert password is not None
    (user,) = db.agregados
    assert (user.username, user.email, user.role) == (USUARIO, EMAIL, "super_admin")
    assert user.is_active is True
    assert user.tenant_id == DEFAULT_TENANT_ID
    assert db.commits == 1


def test_must_change_password_queda_activado(ocupacion, evento):
    db = _DB()
    cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL)
    assert db.agregados[0].must_change_password is True


def test_la_contrasena_es_de_alta_entropia_y_cumple_la_politica(ocupacion, evento):
    passwords = set()
    for _ in range(20):
        db = _DB()
        passwords.add(cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL))
    assert len(passwords) == 20, "cada invocación genera una contraseña distinta"
    for p in passwords:
        validar_password(p)  # no levanta: cumple el mínimo del producto
        assert len(p) >= 32 and len(p) >= MIN_PASSWORD_LEN
        assert len(p.encode()) <= 72, "bcrypt sólo mira 72 bytes: entropía recortada sería mentira"


def test_se_guarda_el_hash_nunca_la_contrasena(ocupacion, evento):
    db = _DB()
    password = cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL)
    guardado = db.agregados[0].password_hash
    assert password not in guardado
    assert guardado.startswith("$2")
    assert verify_password(password, guardado)


def test_la_auditoria_es_metadata_only_y_viaja_en_la_misma_transaccion(ocupacion, evento):
    db = _DB()
    cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL)

    evento.assert_called_once()
    args, kwargs = evento.call_args
    assert args == (db, auth_events.AUTH_BOOTSTRAP_SUPER_ADMIN)
    assert kwargs["target_user_id"] == str(db.agregados[0].id)
    assert kwargs["new_role"] == "super_admin"
    assert kwargs["tenant_id"] == DEFAULT_TENANT_ID
    assert kwargs.get("actor_user_id") is None, "nadie estaba autenticado: lo corre el operador"
    # Sólo ids y literales de rol (constitución, C1): jamás usuario, email ni contraseña.
    valores = " ".join(str(v) for v in (*args[1:], *kwargs.values()))
    assert USUARIO not in valores and EMAIL not in valores
    assert db.commits == 1, "insert + evento se confirman juntos"


def test_el_evento_de_bootstrap_de_super_admin_es_distinto_del_del_admin():
    assert auth_events.AUTH_BOOTSTRAP_SUPER_ADMIN == "auth_bootstrap_super_admin"
    assert auth_events.AUTH_BOOTSTRAP_SUPER_ADMIN != auth_events.AUTH_BOOTSTRAP_ADMIN


# ── Idempotencia y rechazos ─────────────────────────────────────────────────────────


def test_si_ya_hay_un_super_admin_no_crea_nada(ocupacion, evento):
    ocupacion["hay_super_admin"] = True
    db = _DB()

    assert cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL) is None

    assert db.agregados == [] and db.commits == 0
    evento.assert_not_called()


def test_usuario_o_email_ocupados_se_rechazan_sin_ascender_a_nadie(ocupacion, evento):
    ocupacion["ocupado"] = "usuario"
    db = _DB()
    with pytest.raises(cli.AltaRechazada, match="usuario"):
        cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL)
    assert db.agregados == [] and db.commits == 0
    evento.assert_not_called()


@pytest.mark.parametrize("email", ["sin-arroba", "x@host.local", "", "a@b"])
def test_email_invalido_se_rechaza(ocupacion, evento, email):
    """El response de `GET /users` es `EmailStr`: un email que no lo cumple dejaría la
    lista de usuarios rota para todos (bug conocido del bootstrap con `.local`)."""
    db = _DB()
    with pytest.raises(cli.AltaRechazada, match="email"):
        cli.crear_super_admin(db, usuario=USUARIO, email=email)
    assert db.agregados == []


@pytest.mark.parametrize("usuario", ["", "   "])
def test_usuario_vacio_se_rechaza(ocupacion, evento, usuario):
    db = _DB()
    with pytest.raises(cli.AltaRechazada, match="usuario"):
        cli.crear_super_admin(db, usuario=usuario, email=EMAIL)
    assert db.agregados == []


def test_carrera_perdida_en_el_commit_se_reporta_como_rechazo(ocupacion, evento):
    """Dos invocaciones a la vez: la restricción UNIQUE del esquema es la autoridad final."""
    db = _DB()
    db.fallar_commit = IntegrityError("insert", {}, Exception("duplicate key"))
    with pytest.raises(cli.AltaRechazada):
        cli.crear_super_admin(db, usuario=USUARIO, email=EMAIL)
    assert db.rollbacks == 1


# ── El comando: stdout, códigos de salida, "sólo si se lo invoca" ───────────────────


@pytest.fixture
def sesion(monkeypatch):
    db = _DB()
    monkeypatch.setattr(cli, "SessionLocal", lambda: db)
    return db


def test_la_contrasena_sale_UNA_vez_por_stdout_como_PASSWORD_y_nunca_por_stderr(
        sesion, ocupacion, evento, capsys):
    rc = cli._main(["crear-super-admin", "--username", USUARIO, "--email", EMAIL])

    salida = capsys.readouterr()
    assert rc == 0
    password = _password_de(salida.out)
    assert salida.out == f"PASSWORD={password}\n", "stdout lleva SÓLO esa línea"
    assert salida.out.count(password) == 1, "se imprime una sola vez"
    assert password not in salida.err
    assert verify_password(password, sesion.agregados[0].password_hash)


def test_la_contrasena_no_va_a_los_logs(sesion, ocupacion, evento, caplog, capsys):
    caplog.set_level("DEBUG")
    cli._main(["crear-super-admin", "--username", USUARIO, "--email", EMAIL])
    assert _password_de(capsys.readouterr().out) not in caplog.text


def test_usuario_sigue_aceptado_como_alias_de_username(sesion, ocupacion, evento):
    assert cli._main(["crear-super-admin", "--usuario", USUARIO, "--email", EMAIL]) == 0
    assert sesion.agregados[0].username == USUARIO


def test_ya_existente_sale_3_con_mensaje_y_sin_contrasena(sesion, ocupacion, evento, capsys):
    ocupacion["hay_super_admin"] = True

    rc = cli._main(["crear-super-admin", "--username", USUARIO, "--email", EMAIL])

    salida = capsys.readouterr()
    assert rc == cli.SALIDA_YA_EXISTE == 3, "el instalador distingue «ya existe» de un error"
    assert "ya existe un super_admin" in salida.err.lower()
    assert salida.out == ""
    assert sesion.agregados == []


def test_ya_existente_es_cualquier_super_admin_no_solo_el_username_dado(sesion, ocupacion,
                                                                       evento):
    ocupacion["hay_super_admin"] = True
    assert cli._main(["crear-super-admin", "--username", "otro-nombre",
                      "--email", "x@example.com"]) == 3


def test_rechazo_sale_distinto_de_0_con_mensaje_claro(sesion, ocupacion, evento, capsys):
    ocupacion["ocupado"] = "email"

    rc = cli._main(["crear-super-admin", "--username", USUARIO, "--email", EMAIL])

    salida = capsys.readouterr()
    assert rc == 1
    assert "email" in salida.err
    assert salida.out == ""


def test_username_y_email_son_obligatorios(sesion):
    with pytest.raises(SystemExit) as exc:
        cli._main(["crear-super-admin", "--username", USUARIO])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        cli._main([])


# ── resetear-super-admin ────────────────────────────────────────────────────────────


@pytest.fixture
def super_admin(monkeypatch):
    user = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=USUARIO, email=EMAIL,
                password_hash=cli.hash_password("contraseña-vieja-2026"), role="super_admin",
                is_active=True, must_change_password=False)
    encontrados = [user]
    monkeypatch.setattr(cli, "_super_admins_con_username", lambda db, u: list(encontrados))
    return user, encontrados


def test_resetear_cambia_el_hash_fuerza_el_cambio_y_audita(super_admin, evento):
    user, _ = super_admin
    db = _DB()

    password = cli.resetear_super_admin(db, usuario=USUARIO)

    assert verify_password(password, user.password_hash)
    assert not verify_password("contraseña-vieja-2026", user.password_hash)
    assert user.must_change_password is True
    assert db.commits == 1
    args, kwargs = evento.call_args
    assert args == (db, auth_events.AUTH_SUPER_ADMIN_PASSWORD_RESET)
    assert kwargs["target_user_id"] == str(user.id)
    assert kwargs["tenant_id"] == user.tenant_id
    valores = " ".join(str(v) for v in (*args[1:], *kwargs.values()))
    assert password not in valores and USUARIO not in valores and EMAIL not in valores


def test_resetear_genera_contrasenas_de_alta_entropia_y_distintas(super_admin, evento):
    passwords = {cli.resetear_super_admin(_DB(), usuario=USUARIO) for _ in range(10)}
    assert len(passwords) == 10
    assert all(len(p) >= 32 and len(p.encode()) <= 72 for p in passwords)


def test_resetear_usuario_inexistente_o_que_no_es_super_admin_se_rechaza(monkeypatch, evento):
    monkeypatch.setattr(cli, "_super_admins_con_username", lambda db, u: [])
    db = _DB()
    with pytest.raises(cli.AltaRechazada, match="super_admin"):
        cli.resetear_super_admin(db, usuario="tenant-admin-o-nadie")
    assert db.commits == 0
    evento.assert_not_called()


def test_resetear_username_ambiguo_no_resetea_ninguno(super_admin, evento):
    user, encontrados = super_admin
    encontrados.append(User(id=uuid.uuid4(), username=USUARIO, role="super_admin",
                            password_hash="x", email="b@example.com"))
    db = _DB()
    hash_antes = user.password_hash
    with pytest.raises(cli.AltaRechazada, match="más de un"):
        cli.resetear_super_admin(db, usuario=USUARIO)
    assert user.password_hash == hash_antes and db.commits == 0


def test_resetear_por_cli_imprime_PASSWORD_una_vez_y_sale_0(sesion, super_admin, evento,
                                                            capsys):
    rc = cli._main(["resetear-super-admin", "--username", USUARIO])

    salida = capsys.readouterr()
    assert rc == 0
    password = _password_de(salida.out)
    assert salida.out == f"PASSWORD={password}\n" and password not in salida.err
    assert verify_password(password, super_admin[0].password_hash)


def test_resetear_por_cli_rechazo_sale_1_sin_stdout(sesion, monkeypatch, evento, capsys):
    monkeypatch.setattr(cli, "_super_admins_con_username", lambda db, u: [])

    rc = cli._main(["resetear-super-admin", "--username", "nadie"])

    salida = capsys.readouterr()
    assert rc == 1 and salida.out == "" and "nadie" in salida.err


def test_resetear_exige_username(sesion):
    with pytest.raises(SystemExit) as exc:
        cli._main(["resetear-super-admin"])
    assert exc.value.code == 2


def test_nada_de_la_app_invoca_el_comando():
    """«No crea nada si no se lo invoca»: el único lugar que llama a `crear_super_admin` es
    el propio comando (ni el arranque, ni una migración, ni un endpoint)."""
    src = Path(__file__).resolve().parents[2] / "src"
    invocan = [str(p.relative_to(src)) for p in src.rglob("*.py")
               if p.name != "cli.py" and "crear_super_admin" in p.read_text(encoding="utf-8")]
    assert invocan == []
    migraciones = Path(__file__).resolve().parents[2] / "alembic"
    assert [p.name for p in migraciones.rglob("*.py")
            if "crear_super_admin" in p.read_text(encoding="utf-8")] == []
