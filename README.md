# Basa Secure AI Gateway (by basa dev)

Una pasarela (gateway) de Inteligencia Artificial segura, optimizada y de marca blanca diseñada para la gobernanza de datos médicos y el control de costos en sistemas de salud.

## Arquitectura de Contenedores

El proyecto está orquestado usando **Docker Compose** y consta de 6 servicios aislados:

1. **`basa-frontend`**: Interfaz de usuario interactiva construida con React, Vite, Tailwind CSS y Framer Motion.
2. **`basa-backend`**: API wrapper construida con FastAPI (Python) que gestiona presupuestos, ejecuta el enmascaramiento reversible y las políticas regulatorias.
3. **`basa-litellm`**: Motor de enrutamiento interno de modelos (OpenAI, Anthropic).
4. **`basa-db`**: Base de datos PostgreSQL para almacenar usuarios, presupuestos y logs de auditoría.
5. **`presidio-analyzer`**: Microservicio de Microsoft Presidio para detección de entidades PII/PHI.
6. **`presidio-anonymizer`**: Microservicio de Microsoft Presidio para desidentificación.

---

## Características Principales

* **Control de Presupuestos (US1)**: Límites de dinero (USD) y tokens asignables a nivel de usuario o grupo de trabajo, validados en tiempo real.
* **Privacidad Reversible (US2)**: Detección local de DNI, CUIL, nombres y datos de salud mediante Presidio, con enmascaramiento antes del envío al LLM y restauración automática en la respuesta.
* **Optimización de Contexto (Headroom)**: Compresión inteligente opcional de prompts extensos en local para ahorrar entre el 60% y el 95% de tokens.
* **Cumplimiento Regulatorio (US3)**: Residencia de datos forzada en la Unión Europea (GDPR) y auditoría/bloqueo de consultas de alto riesgo (AI Act).
* **Logs de Auditoría Seguros (US4)**: Registro inmutable de transacciones sin almacenar datos personales de pacientes.
* **Playground Interactivo (US5)**: Interfaz de chat con una animación visual en tiempo real de la pila de capas de seguridad que atraviesa el prompt.

---

## Inicio Rápido (Desarrollo Local)

### 1. Clonar y Configurar Entorno
Copie el archivo de ejemplo de variables de entorno y complete sus credenciales de APIs de LLMs si desea probar llamadas reales (de lo contrario, el sistema utilizará respuestas simuladas automáticas para que el Playground sea funcional inmediatamente):

```bash
cp .env.example .env
```

Edite el archivo `.env` e ingrese sus claves:
```env
OPENAI_API_KEY=su_clave_aquí
ANTHROPIC_API_KEY=su_clave_aquí
```

### 2. Levantar los Contenedores
Ejecute el siguiente comando para construir y levantar los 6 servicios en segundo plano:

```bash
docker-compose up --build -d
```

### 3. Acceso a las Aplicaciones

> **Puertos de basa-guardian**: desplazados para coexistir con el repo demo
> (gatelite, que ocupa 5432/4000/8080/8081 y debe seguir corriendo en paralelo).

* **Panel de Control y Playground (Frontend)**: [http://localhost:8090](http://localhost:8090)
* **Documentación de la API (Swagger)**: [http://localhost:8091/docs](http://localhost:8091/docs)
* **Motor (interno)**: [http://localhost:4010/health/readiness](http://localhost:4010/health/readiness)
* **PostgreSQL (host)**: `localhost:5433`

---

## Verificación de Funcionalidades

### Prueba del Pipeline Seguro (Playground)
1. Ingrese a [http://localhost:5173](http://localhost:5173).
2. Escriba un mensaje con datos personales en el chat del Playground, por ejemplo:
   > *"El paciente Juan Pérez con DNI 22334455 tiene fiebre alta y dolor de cabeza."*
3. Presione Enviar. Verá en el panel derecho cómo el prompt pasa de forma secuencial por la capa de enmascaramiento de Presidio (reemplazando `Juan Pérez` por `[PERSON_0]` y `22334455` por `[DNI_0]`), la compresión de Headroom, las validaciones de GDPR/AI Act, y finalmente cómo la respuesta del modelo se desenmascara restaurando el nombre del paciente en pantalla.
