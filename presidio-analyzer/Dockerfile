# Imagen propia (spec 016): presidio-analyzer como librería Python + modelo spaCy
# español, servida por un thin FastAPI (app.py) con el contrato HTTP propio del
# producto. Pin de versiones vía requirements.txt (mismo criterio que litellm por
# digest — acá por versión exacta de paquete, ver Principio VI/VII).
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download es_core_news_md

COPY app.py .
COPY conf/ conf/

EXPOSE 3000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3000"]
