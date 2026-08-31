# 🐳 Elea Custom Chat Standalone (Docker Aislado)

Este módulo contiene el despliegue del **Chat de Elea empaquetado en un contenedor Docker totalmente independiente** del core hub de Guardian, corriendo en el puerto **`8095`**.

---

## 🎯 Características Principal

1. **Aislamiento Total:** Corre en su propio contenedor `guardian-elea-custom-chat` en el puerto **`http://localhost:8095`**.
2. **Capacidad Conversacional Dual:**
   - **Chat Directo:** Consultas conversacionales generales.
   - **Integración API / MCP en Segundo Plano:** Se conecta con:
     - **AnythingLLM (`:3001`):** Consultas RAG documentales con citas explicitar de página y documento.
     - **DB-GPT (`:5670`) / DuckDB:** Cruces y cómputos relacionales en archivos CSV y Excel.
     - **Presenton AI (`:3050`):** Generación automática de presentaciones y documentos.

---

## 🚀 Despliegue con Docker Compose

```bash
cd installations/11_elea_standalone_chat
docker compose up -d --build
```

Acceder desde el navegador a: **[http://localhost:8095](http://localhost:8095)**.
