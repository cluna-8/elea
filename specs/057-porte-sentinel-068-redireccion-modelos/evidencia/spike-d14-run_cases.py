"""Runner en Python de los casos de spike053/run_cases.sh (la imagen del motor no trae curl). Corre DENTRO de la imagen fijada."""
import json, subprocess, sys, time, os, urllib.request, urllib.error, importlib.metadata
P = "http://127.0.0.1:18900"
def start(cmd, **kw):
    return subprocess.Popen(cmd, stdout=open("/tmp/work/%s.log" % kw.pop("name"), "w"), stderr=subprocess.STDOUT, cwd="/tmp/work", **kw)
print("litellm", importlib.metadata.version("litellm"))
procs = [start([sys.executable, "fake_upstream.py", "real", "18901"], name="real"),
         start([sys.executable, "fake_upstream.py", "evil", "18902"], name="evil"),
         start(["litellm", "--config", "config.yaml", "--host", "127.0.0.1", "--port", "18900"], name="proxy", env={**os.environ, "OPENAI_API_KEY": ""})]
for _ in range(120):
    try:
        urllib.request.urlopen(P + "/health/liveliness", timeout=2); break
    except Exception: time.sleep(1)
else:
    print("PROXY NO ARRANCO"); print(open("/tmp/work/proxy.log").read()[-2000:]); sys.exit(2)
def hits(n): 
    try: return sum(1 for _ in open(f"/tmp/work/hits_{n}.jsonl"))
    except FileNotFoundError: return 0
def last_real():
    try: return open("/tmp/work/hits_real.jsonl").read().strip().splitlines()[-1]
    except Exception: return None
def post(path, key, body, extra=None, stream=False, headers_extra=None):
    h = {"content-type": "application/json", **(headers_extra or {})}
    if key is not None: h["Authorization"] = "Bearer " + key
    h.update(extra or {})
    req = urllib.request.Request(P + path, data=json.dumps(body).encode(), headers=h, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=60); return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
def caso(nombre, code_body, antes=None):
    code, body = code_body
    print(f"{nombre}\n   → HTTP {code} {body[:230].strip()!r}\n   hits real: {hits('real')} | evil: {hits('evil')}\n   último real: {last_real()}")
AUTH = {"x-redirect-auth": "firma-valida"}
msg = [{"role": "user", "content": "hola"}]
caso("A1 comodín, no-stream, sk-open, con autorización interna", post("/v1/chat/completions", "sk-open", {"model": "rdx-openai-compat/gpt-destino", "messages": msg}, AUTH))
caso("A2 comodín, stream", post("/v1/chat/completions", "sk-open", {"model": "rdx-openai-compat/gpt-destino", "stream": True, "messages": msg}, AUTH))
caso("A3 cara Anthropic /v1/messages → comodín (openai/*), stream", post("/v1/messages", "sk-open", {"model": "rdx-openai-compat/gpt-destino", "max_tokens": 20, "stream": True, "messages": msg}, {**AUTH, "anthropic-version": "2023-06-01"}))
caso("A3b cara Anthropic /v1/messages → familia chat (hosted_vllm/*), no-stream", post("/v1/messages", "sk-open", {"model": "rdx-chatcompat/qwen-destino", "max_tokens": 20, "messages": msg}, {**AUTH, "anthropic-version": "2023-06-01"}))
caso("B1 anti-desvío: cliente manda api_base/api_key propios (evil)", post("/v1/chat/completions", "sk-open", {"model": "rdx-openai-compat/gpt-destino", "api_base": "http://127.0.0.1:18902/v1", "api_key": "clave-del-atacante", "messages": msg}, AUTH))
caso("B2 sin autorización interna → debe rechazar", post("/v1/chat/completions", "sk-open", {"model": "rdx-openai-compat/gpt-destino", "messages": msg}))
caso("B3 línea base 'pro' (sin guard): ¿el motor acepta api_base del cliente?", post("/v1/chat/completions", "sk-open", {"model": "pro", "api_base": "http://127.0.0.1:18902/v1", "messages": msg}))
caso("C1 sk-limited (solo 'pro') pide rdx-* con autorización → ¿el motor aplica la lista?", post("/v1/chat/completions", "sk-limited", {"model": "rdx-openai-compat/gpt-destino", "messages": msg}, AUTH))
caso("C2 sk-limited pide 'pro'", post("/v1/chat/completions", "sk-limited", {"model": "pro", "messages": msg}))
req = urllib.request.Request(P + "/v1/models", headers={"Authorization": "Bearer sk-open"})
body = urllib.request.urlopen(req, timeout=30).read().decode()
ids = [m["id"] for m in json.loads(body)["data"]]
print("D1 /v1/models con sk-open:", len(ids), "ids;", [i for i in ids if i.startswith("rdx-")][:6], "…")
for p in procs: p.terminate()
