# Motor tabular de Eleia Hub (spec 050, FR-020..026): Excel/CSV → DuckDB → SQL solo lectura.
# Sin puertos publicados al host; su única salida a un modelo es Guardian (`engine:4000/v1`).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Usuario sin privilegios: el servicio solo escribe en /data (volumen).
RUN useradd --system --uid 10001 --create-home tabular \
    && mkdir -p /data && chown -R tabular:tabular /data /app
USER tabular

ENV TABULAR_DATA_DIR=/data
EXPOSE 8090

HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
