FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for psycopg2 and compiling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# `heads` sólo con migraciones de extensiones (ALEMBIC_EXTRA_VERSION_LOCATIONS); si no, `head`.
CMD ["sh", "-c", "t=head; [ -n \"$ALEMBIC_EXTRA_VERSION_LOCATIONS\" ] && t=heads; alembic upgrade $t && uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"]
