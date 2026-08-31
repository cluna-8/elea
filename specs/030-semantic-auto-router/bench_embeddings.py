import urllib.request as u, json, math

def embed(model, texts, prefix=''):
    body = json.dumps({'model': model, 'input': [prefix + t for t in texts]}).encode()
    r = u.urlopen(u.Request('http://localhost:11434/api/embed', data=body,
                            headers={'Content-Type': 'application/json'}), timeout=180)
    return json.loads(r.read())['embeddings']

def cos(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0

cfg = json.load(open('/Users/drzuzz/code/SENTINEL-DEV/llm-guardian/litellm/auto_router.json'))
routes = cfg['routes']

# Batería: (query, ruta esperada) — premium = código/análisis, mini = redacción/resumen, None = default
TESTS = [
    ('escribí una función en python que ordene una lista de fechas', 'azure-gpt-5.1-chat'),
    ('tengo un NullPointerException en esta línea, ¿por qué?', 'azure-gpt-5.1-chat'),
    ('analizá estos resultados de ventas y decime qué patrón ves', 'azure-gpt-5.1-chat'),
    ('¿qué riesgos tiene migrar la base de datos a la nube?', 'azure-gpt-5.1-chat'),
    ('resumime este documento en tres puntos', 'azure-gpt-5.4-mini'),
    ('traducí este párrafo al inglés', 'azure-gpt-5.4-mini'),
    ('redactá un email cordial para rechazar una propuesta', 'azure-gpt-5.4-mini'),
    ('hola, ¿qué tal?', None),
    ('gracias, nos vemos mañana', None),
]

CANDIDATES = [('nomic-embed-text', ''), ('granite-embedding:278m', ''), ('qwen3-embedding:0.6b', '')]

all_utts = [(r['name'], t, r.get('score_threshold', 0.45)) for r in routes for t in r['utterances']]
utt_texts = [t for _, t, _ in all_utts]

for model, qprefix in CANDIDATES:
    utt_vecs = embed(model, utt_texts)
    q_vecs = embed(model, [q for q, _ in TESTS], qprefix)
    ok = 0; lines = []
    for (q, expected), qv in zip(TESTS, q_vecs):
        best_name, best_score = None, 0.0
        for (name, _, thr), uv in zip(all_utts, utt_vecs):
            s = cos(qv, uv)
            if s >= thr and s > best_score:
                best_name, best_score = name, s
        hit = (best_name == expected)
        ok += hit
        mark = 'OK ' if hit else 'MAL'
        lines.append(f'  {mark} {q[:44]:46} -> {best_name or "default":22} ({best_score:.2f})')
    print(f'== {model}{" +prefijo" if qprefix else ""}: {ok}/{len(TESTS)} ==')
    for l in lines:
        print(l)
