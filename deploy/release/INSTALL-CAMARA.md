# Instalación Cámara de Comercio — paso a paso

> Piloto on-prem desde pendrive, sin internet. 2026-07-28.
> Guía completa con contexto: `runbook-camara.html` (en este mismo pendrive) o
> https://claude.ai/code/artifact/8a61530b-2dfb-4f04-8ddb-e417402617fc

## Qué hay en el pendrive

| Fichero | Qué es |
|---|---|
| `bundle-camara-comercio.tar.gz` | Stack completo (8 imágenes **x86_64** + instalador + extensión) |
| `camara-comercio-300.lic` | Licencia 300 asientos |
| `INSTALL-CAMARA.md` | Este documento |
| `runbook-camara.html` | Runbook completo (troubleshooting, qué no prometer, etc.) |

La extensión de navegador viaja DENTRO del bundle (`extension-camara-comercio.zip`).

---

## 1 · Chequeos del host (antes de descomprimir nada)

```bash
uname -m
```
Tiene que decir `x86_64`. Si no, frená: es el bundle equivocado (el instalador también se niega solo).

```bash
docker version && docker ps
```
Docker tiene que estar y `docker ps` tiene que andar **sin sudo** (si falla: `sudo usermod -aG docker $USER` y re-login). El plugin `docker compose` NO hace falta — lo trae el bundle y se instala solo si falta.

```bash
df -h /var/lib/docker && free -g && nproc
```
Pide ~10 GB libres; el sidecar NLP carga un modelo en memoria (mejor ≥8 GB RAM).

```bash
sudo ss -tlnp | grep -E ':80 |:443 ' || echo "80 y 443 libres ✅"
```

## 2 · Copiar e instalar (los 2 comandos)

```bash
mkdir -p ~/basa-install && cp /media/*/BASA/bundle-camara-comercio.tar.gz /media/*/BASA/camara-comercio-300.lic ~/basa-install/ && cd ~/basa-install
```
(En Ubuntu de escritorio el pendrive monta en `/media/<usuario>/BASA`; ajustá si difiere.)

```bash
tar xzf bundle-camara-comercio.tar.gz && cd bundle-camara-comercio && ./install.sh ../camara-comercio-300.lic camara
```

Carga las imágenes, puebla volúmenes y levanta el stack. Con puertos ocupados: anteponer `INGRESS_HTTP_PORT=8080 INGRESS_HTTPS_PORT=8443`.

⚠️ **Falsa alarma conocida**: en el PRIMER arranque el motor puede reportarse `unhealthy` — corre sus migraciones. Esperá 2-3 min. **No lo reinicies.**

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'
```
Tienen que quedar **8**: backend, frontend, docs, nlp-analyzer, litellm, ingress, db, redis.

## 3 · Licencia y génesis (ANTES del primer login)

```bash
curl -s http://localhost/api/v1/health/license
```
Esperado: `"status":"active"`. **Anotá el `chain.genesis_license_id`** — es la génesis de auditoría de esta instalación y hay que registrarla del lado Basa.

## 4 · Primer login

Navegador → `http://localhost` (o la IP/dominio de la máquina). Usuario `admin` + la contraseña que escribas — **esa queda** (mínimo 12 caracteres, elegila antes, no delante del cliente).

## 5 · Conectar el modelo local (Ollama del Z2)

**Si el stack quedó EN el mismo Z2 donde corre Ollama**: el modelo por defecto ya apunta ahí; solo asegurate de que Ollama escuche fuera de localhost:

```bash
sudo systemctl edit ollama
```
Añadir en el bloque: `[Service]` → `Environment="OLLAMA_HOST=0.0.0.0"`, y después:

```bash
sudo systemctl restart ollama && ollama list
```

**Si el stack está en otra máquina** (o el nombre del modelo no coincide con `ollama list`): panel admin → **Modelos & Ollama → + Agregar Modelo → + Modelo personalizado** → proveedor «Ollama (Local)», modelo exacto de `ollama list` (ej. `qwen3:4b`), api base `http://IP-DEL-Z2:11434`, sin key.

🔴 **CLAVE — tras CADA alta de modelo por la UI, reiniciar el motor:**

```bash
docker restart camara-litellm-1
```

Si no: el Playground "no hace nada" (es un 400 que la UI no muestra). Orden siempre: **alta → restart → probar**.

## 6 · Usuarios

Panel admin → Usuarios: cada alta pide **contraseña propia de 12+** (se la entregás por canal seguro). Los admins de la Cámara pueden crear los que quieran (300 asientos). Cada persona que use API/herramientas necesita además su **Connection** — la clave se muestra UNA sola vez, copiala en el momento.

## 7 · Extensión de navegador

`chrome://extensions` → Modo desarrollador → «Cargar descomprimida» → carpeta `extension/` del zip descomprimido (la que tiene `manifest.json` a la vista). En el popup: URL del gateway + la clave de esa persona. Exige `https://` salvo `localhost` — si el acceso va por IP de LAN, resolvé dominio interno + TLS de Caddy **al principio de la visita**.

## 8 · Smoke test de la demo

1. Playground → «Escribe un email para Marta Gutiérrez, DNI 28456789A, teléfono 611 234 567»
2. Pestaña **Debugger Técnico** → el JSON de la petición muestra `[PERSON_0]`, `[PASSPORT_0]`, `[PHONE_NUMBER_0]` → **eso es lo que recibió el proveedor** (la respuesta se des-enmascara sola: que se vean los datos reales en la respuesta es lo CORRECTO)
3. Usá formatos españoles en la demo (DNI con letra, IBAN, email) — verificados. Coste de modelo local personalizado puede mostrar una tarifa conservadora: es cosmético, decilo antes de que pregunten.

## 9 · Parar / reiniciar

Siempre con los `--env-file` (sin ellos compose falla):

```bash
cd ~/basa-install/bundle-camara-comercio && docker compose -p camara -f compose.prod.yml --profile selfhosted --env-file profile/instance.env --env-file profile/secrets.env down
```

## 10 · NUNCA

- **NO** correr `issue_dev_license.py` (invalida la licencia viva).
- **NO** "limpiar" `secrets.env` (sin `BASA_ALLOW_DEV_LICENSE=true` no se puede dar de alta nada).
- **NO** reiniciar el motor porque diga `unhealthy` en el primer arranque.

## Troubleshooting exprés

| Síntoma | Causa |
|---|---|
| Playground «no hace nada» tras alta de modelo | Falta `docker restart camara-litellm-1` |
| `Cannot connect to host host.docker.internal:11434` | Ollama sin `OLLAMA_HOST=0.0.0.0`, o stack en otra máquina → alta por UI con IP |
| 401 en todo con clave válida | Motor sin `BASA_IDENTITY_URL` |
| Detecta emails pero no nombres | El sidecar NLP no está arriba |
| 403 «rollback de reloj» al crear usuarios | Se cura solo en ≤5 min (corregido en este build) |

Logs: `docker logs --tail 100 camara-backend-1` (ídem `camara-litellm-1`, `camara-nlp-analyzer-1`).

---

## Anexo · Sin pendrive

Los mismos 4 ficheros viven en DOS sitios más: la carpeta `~/piloto-camara-sede/` del Mac
de JF, y `/root/piloto-camara/` del VPS de basa-dev.

### A · Desde el Mac, por la LAN de la sede (vía preferida)

En el Mac (conectado a la misma red que el servidor):

```bash
cd ~/piloto-camara-sede && python3 -m http.server 8000
```

Anotá la IP del Mac (`ipconfig getifaddr en0`). En el servidor de la sede:

```bash
mkdir -p ~/basa-install && cd ~/basa-install && for f in bundle-camara-comercio.tar.gz camara-comercio-300.lic INSTALL-CAMARA.md; do wget "http://IP-DEL-MAC:8000/$f"; done
```

Cortá el `http.server` con Ctrl-C en cuanto termine y seguí en el paso 2.

### B · Desde el VPS (si el Mac no está disponible)

Desde cualquier máquina con la clave SSH de basa-dev:

```bash
scp vps:/root/piloto-camara/\{bundle-camara-comercio.tar.gz,camara-comercio-300.lic\} .
```

Si el **servidor de la sede** tiene que bajarlo directo (sin clave SSH): en el VPS hay una
copia **cifrada** (`bundle-camara-comercio.tar.gz.enc` — el bundle lleva los secretos de la
instalación, no viaja en claro por HTTP). Servirla temporal:

```bash
ssh vps 'cd /root/piloto-camara && timeout 1800 python3 -m http.server 3004'
```

En el servidor de la sede (la passphrase la tiene JF):

```bash
wget http://95.217.129.250:3004/bundle-camara-comercio.tar.gz.enc && openssl enc -d -aes-256-cbc -pbkdf2 -in bundle-camara-comercio.tar.gz.enc -out bundle-camara-comercio.tar.gz
```

El `http.server` muere solo a los 30 min (`timeout 1800`); la licencia (495 B) pasásela
aparte (a mano, por el chat del móvil, como sea — es texto).
