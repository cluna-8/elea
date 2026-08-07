# ADR-0001: Los países se implementan como perfiles de configuración, no como ramas

**Fecha:** 2026-08-05 · **Estado:** aceptado
**Decisores:** Cristian

## Contexto

Guardian se venderá en Argentina, España y Colombia, con compliance, precios y entidades PII distintas por jurisdicción (DNI/NIF/cédula). Surgió la pregunta de si conviene una rama por país. El repo ya cuenta con perfiles de cliente en `deploy/clients/`, overlays white-label y políticas de compliance configurables (spec 027).

## Decisión

Cada país es un **perfil de configuración** (policy pack): políticas de compliance activas, entidades PII locales, precios e idioma, aplicado al crear el perfil del cliente en `deploy/clients/`. Un solo código en `main`, N perfiles.

## Alternativas consideradas

- **Rama por país**: descartada — divergencia inevitable, cada fix se mergea N veces, versiones incomparables entre clientes.
- **Fork/repo por país**: descartada — mismo problema agravado, rompe la fuente única de licensing y el kit del partner.

## Consecuencias

- Agregar un país = escribir un perfil, no tocar código. Escala el negocio sin escalar el mantenimiento.
- Si un país exige lógica que no existe, se implementa en `main` detrás de configuración, con su propio ADR si es estructural.
- Queda prohibido crear ramas o forks por país o por cliente.
