"""Configuración por variables de entorno (contrato 03-motores.md §3.2 de la spec 050)."""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    # Auth Hub → tabular. Obligatoria: sin token el servicio rechaza todo (FR-020).
    internal_token: str = os.getenv("TABULAR_INTERNAL_TOKEN", "")
    # tabular → Guardian engine (API OpenAI). Nunca la llave maestra (FR-050).
    engine_url: str = os.getenv("TABULAR_ENGINE_URL", "http://engine:4000/v1").rstrip("/")
    engine_key: str = os.getenv("TABULAR_ENGINE_VIRTUAL_KEY", "")
    # Nombre REAL del catálogo: el engine no conoce `auto` (spec 050 Parte A.3).
    model: str = os.getenv("TABULAR_MODEL", "azure-gpt-5.4-mini")
    engine_timeout_s: int = _int("TABULAR_ENGINE_TIMEOUT_S", 30)

    data_dir: str = os.getenv("TABULAR_DATA_DIR", "/data")
    max_file_mb: int = _int("TABULAR_MAX_FILE_MB", 50)
    query_timeout_s: int = _int("TABULAR_QUERY_TIMEOUT_S", 20)
    memory_limit: str = os.getenv("TABULAR_MEMORY_LIMIT", "1GB")
    threads: int = _int("TABULAR_THREADS", 2)
    max_rows: int = _int("TABULAR_MAX_ROWS", 500)        # LIMIT forzado (FR-023)
    sample_rows: int = _int("TABULAR_SAMPLE_ROWS", 5)     # muestra por tabla en el prompt
    answer_rows: int = _int("TABULAR_ANSWER_ROWS", 50)    # filas que ve el modelo al redactar (FR-024)
    # Historial (spec 051): últimos N turnos literales al modelo; resumen de lo anterior cada M.
    history_window: int = _int("TABULAR_HISTORY_WINDOW", 5)
    history_summary_every: int = _int("TABULAR_HISTORY_SUMMARY_EVERY", 5)
    history_rows: int = _int("TABULAR_HISTORY_ROWS", 50)  # filas guardadas por turno


settings = Settings()
