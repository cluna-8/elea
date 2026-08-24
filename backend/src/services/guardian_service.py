import os
import re
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from ..models.guardian import Guardian
from .audit_service import record_nlp_degradation
from .presidio_service import PresidioService, NlpUnavailableError, policy

logger = logging.getLogger("basa-secure-gateway.guardian")

class GuardianService:
    @staticmethod
    def get_or_create_default_guardians(db: Session) -> List[Guardian]:
        guardians = db.query(Guardian).all()
        
        # Migración-on-read del guardián PII. REGLA: solo corrige el valor que dejó
        # una versión anterior del seed; jamás pisa una edición del administrador.
        # (Sin esta disciplina, cada `GET /guardians` — que llama a este método —
        # revertía la configuración del cliente y su UI "se desconfiguraba sola".)
        pii_g = db.query(Guardian).filter(Guardian.guardian_type == "pii_masking").first()
        if pii_g:
            new_config = dict(pii_g.config or {})
            updated = False

            # Nombres propios del piloto: se siembran UNA sola vez, cuando la clave
            # nunca existió. Si el admin los borró, `custom_names` está presente (aunque
            # sea vacía) y no se vuelve a tocar.
            if "custom_names" not in new_config:
                new_config["custom_names"] = ["Pedro", "Cristian"]
                updated = True

            # spec 016 T028/T029: instalaciones seedeadas ANTES de la corrección de
            # región (Europa, no Argentina) se quedaron con DNI/CUIL en `entities` —
            # un tipo que el detector real ya no produce, así que nunca se enmascaraba
            # nada de esa categoría en silencio. Se migra SOLO desde el default viejo
            # exacto: cualquier otra lista es una elección del cliente y se respeta.
            legacy_ar_entities = {"PERSON", "DNI", "CUIL", "EMAIL_ADDRESS", "PHONE_NUMBER"}
            eu_entities = ["PERSON", "ES_NIF", "ES_NIE", "PASSPORT", "EMAIL_ADDRESS",
                           "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD"]
            current_entities = new_config.get("entities")
            if current_entities is None or set(current_entities) == legacy_ar_entities:
                new_config["entities"] = eu_entities
                updated = True

            if updated:
                pii_g.config = new_config
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(pii_g, "config")
                db.commit()
                # Refresh list
                guardians = db.query(Guardian).all()

        # If we have less than 9 guardians, re-seed to get the full catalog
        if len(guardians) < 9:
            # Delete existing to prevent duplicates
            db.query(Guardian).delete()
            db.commit()
            
            # Seed full LiteLLM-compliant guardians catalog
            g1 = Guardian(
                name="Enmascaramiento de Datos Médicos (PII/PHI)",
                guardian_type="pii_masking",
                is_active=True,
                config={
                    # Alineado con el default de SecurityPolicy.entity_configs (spec 016,
                    # región eu/España): DNI/CUIL eran argentinos, ya no aplican por default
                    # (T028/T029 — antes este catálogo divergía en silencio del real).
                    "entities": ["PERSON", "ES_NIF", "ES_NIE", "PASSPORT", "EMAIL_ADDRESS",
                                "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD"],
                    "action": "MASK",
                    "custom_names": ["Pedro", "Cristian", "Juan Pérez", "María López", "Carlos Rodríguez"],
                    # issue #63: qué hacer si el motor NLP no responde. Se siembra EXPLÍCITO
                    # aunque el default del resolutor ya sea el mismo, para que el admin vea
                    # la postura escrita en la pantalla en vez de tener que deducirla de una
                    # clave ausente. Deliberadamente NO hay migración-on-read arriba: en una
                    # instalación existente la clave ausente resuelve `block` igual, y
                    # escribirla sería pisar la config de un cliente que quizá ya la editó.
                    "nlp_fail_mode": "block",
                    # Región de STRUCTURED_ID_PATTERNS_BY_REGION de ESTE tenant (extensión
                    # de spec 016 para países reales). H3 del gate de #137: acá el criterio
                    # «igual que nlp_fail_mode» NO transfiere tal cual — `nlp_fail_mode`
                    # siembra una CONSTANTE porque no hay env equivalente (sembrarla es
                    # no-op); `region` SÍ tiene un default de instalación (`BASA_ENTITY_
                    # REGION`), así que sembrar el literal `"eu"` a ciegas ANULABA ese
                    # default en cualquier instalación no-EU desde el primer `GET
                    # /guardians`. Se siembra el valor RESUELTO de la instalación en este
                    # instante (visible en pantalla, mismo espíritu que `nlp_fail_mode`),
                    # no un literal — instalaciones nuevas con `BASA_ENTITY_REGION=latam_ar`
                    # nacen con `latam_ar`, no con `eu`. Sin migración-on-read para
                    # instalaciones existentes (mismo criterio que `nlp_fail_mode`): la
                    # clave ausente sigue resolviendo por `BASA_ENTITY_REGION` hasta que un
                    # admin fije el país de este tenant explícitamente.
                    "region": os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION),
                }
            )
            g2 = Guardian(
                name="Filtro de Claves y Secretos de API (Secret Detection)",
                guardian_type="secret_detection",
                is_active=True,
                config={
                    "action": "BLOCK"
                }
            )
            g3 = Guardian(
                name="Enrutamiento de Diagnósticos Sensibles",
                guardian_type="sensitive_routing",
                is_active=False,
                config={
                    # 0km: el vocabulario sensible es DEL CLIENTE (config), el
                    # producto no precarga términos de ningún vertical. Sin
                    # keywords ni destino el guardián no hace nada (nace off).
                    "keywords": [],
                    "on_premise_model": "",
                    "sticky_session": True
                }
            )
            g4 = Guardian(
                name="Filtro de Contenido Inapropiado",
                guardian_type="openai_moderation",
                is_active=False,
                engine_guardrail_name="litellm_content_filter",
                fail_mode="block",
                apply_on="both",
                config={
                    "action": "BLOCK",
                    "categories": ["hate", "harassment", "self-harm", "sexual", "violence"]
                }
            )
            g5 = Guardian(
                name="Protección Anti-Jailbreak y Anti-Inyección",
                guardian_type="lakera_prompt_injection",
                is_active=False,
                engine_guardrail_name="promptguard",
                fail_mode="block",
                apply_on="pre_call",
                config={
                    "action": "BLOCK",
                    "threshold": 0.7
                }
            )
            g6 = Guardian(
                name="Moderación de Seguridad (Azure)",
                guardian_type="azure_content_safety",
                is_active=False,
                engine_guardrail_name="azure/text_moderations",
                fail_mode="block",
                apply_on="both",
                config={
                    "action": "BLOCK",
                    "severity_threshold": 4
                }
            )
            g7 = Guardian(
                name="Escudo Anti-Jailbreak (Azure)",
                guardian_type="llamaguard_moderations",
                is_active=False,
                engine_guardrail_name="azure/prompt_shield",
                fail_mode="block",
                apply_on="pre_call",
                config={
                    "action": "BLOCK"
                }
            )
            g8 = Guardian(
                name="Políticas de Temas Restringidos (AWS)",
                guardian_type="bedrock_guardrails",
                is_active=False,
                engine_guardrail_name="bedrock_guardrails",
                fail_mode="block",
                apply_on="pre_call",
                config={
                    "action": "BLOCK",
                    "blocked_topics": ["consejo financiero", "asesoría legal no autorizada"]
                }
            )
            
            g9 = Guardian(
                name="Detección NLP de PII/PHI (Presidio)",
                guardian_type="presidio",
                is_active=False,
                config={
                    "analyzer_url": "",
                    "anonymizer_url": "",
                    "language": "es",
                    "entities": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "CREDIT_CARD", "IBAN_CODE"],
                    "action": "MASK",
                }
            )

            db.add_all([g1, g2, g3, g4, g5, g6, g7, g8, g9])
            db.commit()
            guardians = [g1, g2, g3, g4, g5, g6, g7, g8, g9]
            
        return guardians

    @staticmethod
    async def process_prompt(
        db: Session,
        prompt: str,
        selected_model: str,
        overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Processes the prompt through all active guardians in the catalog.
        """
        guardians = GuardianService.get_or_create_default_guardians(db)
        
        processed_prompt = prompt
        routed_model = selected_model
        blocked = False
        block_reason = ""
        placeholder_map = {}
        entities_detected = []
        triggers = []

        # 1. Secret & API Key Detection Guardian
        secret_guardian = next((g for g in guardians if g.guardian_type == "secret_detection" and g.is_active), None)
        is_secret_active = secret_guardian is not None
        if overrides and overrides.get("override_secret_detection") is not None:
            is_secret_active = overrides["override_secret_detection"]

        if is_secret_active:
            patterns = {
                # Captura las keys clásicas `sk-<alfanum>` Y las nuevas `sk-proj-...`
                # (llevan guiones y guiones bajos). Largo mínimo 20 para no dar falsos
                # positivos con strings cortos tipo `sk-abc`.
                "OpenAI API Key": r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}",
                "Google API Key": r"AIzaSy[a-zA-Z0-9_-]{33}",
                "Generic Secret": r"Bearer\s+[a-zA-Z0-9\-_\.]{20,}"
            }
            action = secret_guardian.config.get("action", "BLOCK") if secret_guardian else "BLOCK"
            
            for key_type, pattern in patterns.items():
                matches = re.findall(pattern, processed_prompt)
                if matches:
                    if action == "BLOCK":
                        blocked = True
                        block_reason = f"Seguridad: Se bloqueó la petición debido a la detección de claves privadas ({key_type})."
                        triggers.append({
                            "guardian": secret_guardian.name if secret_guardian else "Secret Detector",
                            "action": "BLOCK",
                            "detail": f"Clave detectada: {key_type}"
                        })
                        break
                    elif action == "REDACT":
                        processed_prompt = re.sub(pattern, "[SECRETO_REDACTADO]", processed_prompt)
                        triggers.append({
                            "guardian": secret_guardian.name if secret_guardian else "Secret Detector",
                            "action": "REDACT",
                            "detail": f"Redactada clave: {key_type}"
                        })

        if blocked:
            return {
                "prompt": processed_prompt,
                "model": routed_model,
                "blocked": True,
                "block_reason": block_reason,
                "placeholder_map": placeholder_map,
                "entities_detected": entities_detected,
                "triggers": triggers
            }

        # 2. Sensitive Data Routing Guardian
        routing_guardian = next((g for g in guardians if g.guardian_type == "sensitive_routing" and g.is_active), None)
        is_routing_active = routing_guardian is not None
        if overrides and overrides.get("override_sensitive_routing") is not None:
            is_routing_active = overrides["override_sensitive_routing"]

        if is_routing_active and routing_guardian:
            keywords = routing_guardian.config.get("keywords", [])
            # Sin destino configurado NO se rutea: jamás mandar el request a un
            # modelo que el catálogo del cliente no define (pre-piloto 2026-07-22;
            # el default hardcodeado 'ollama-llama3' era residuo del demo).
            on_premise_model = routing_guardian.config.get("on_premise_model") or ""
            prompt_lower = processed_prompt.lower()
            matched_keywords = [kw for kw in keywords if kw.lower() in prompt_lower]

            if matched_keywords and on_premise_model:
                routed_model = on_premise_model
                triggers.append({
                    "guardian": routing_guardian.name,
                    "action": "REROUTE",
                    "detail": f"Enrutado a modelo local '{on_premise_model}' por términos: {', '.join(matched_keywords)}"
                })
            elif matched_keywords:
                triggers.append({
                    "guardian": routing_guardian.name,
                    "action": "FLAG",
                    "detail": "Términos sensibles detectados pero el guardián no tiene modelo destino configurado — sin reruteo."
                })

        # 3. PII/PHI Masking Guardian (Presidio + Custom Names)
        # issue #119: desempate determinista (la ACTIVA más antigua por `created_at, id`) para
        # coincidir con el escritor del catálogo custom (`entity_catalog_service._pii_guardian`)
        # y con los lectores de tráfico (#104). Sin él, con dos `pii_masking` activos este plano
        # tomaba una fila ARBITRARIA con `next(...)` y podía no ver el vocabulario (entidades/
        # nombres) que el panel escribió en la fila que de verdad gobierna.
        pii_guardian = min(
            (g for g in guardians if g.guardian_type == "pii_masking" and g.is_active),
            key=lambda g: (g.created_at, g.id), default=None)
        is_pii_active = pii_guardian is not None
        if overrides and overrides.get("override_pii_masking") is not None:
            is_pii_active = overrides["override_pii_masking"]

        if is_pii_active:
            entities_to_scan = pii_guardian.config.get("entities", ["PERSON", "DNI", "CUIL", "EMAIL_ADDRESS", "PHONE_NUMBER"]) if pii_guardian else ["PERSON", "DNI", "CUIL", "EMAIL_ADDRESS", "PHONE_NUMBER"]
            action = pii_guardian.config.get("action", "MASK") if pii_guardian else "MASK"
            custom_names = pii_guardian.config.get("custom_names", []) if pii_guardian else []
            # Región de STRUCTURED_ID_PATTERNS_BY_REGION de ESTE tenant (H1 del gate de
            # #137): antes el Playground nunca la resolvía — `analyze_text_http` hardcodeaba
            # `"eu"` y `analyze_text` (el fallback regex) ni tenía el parámetro. Mismo
            # mecanismo que `resolve_nlp_fail_mode`: clave `region` en el `config` del
            # guardián `pii_masking` activo, con el default DE LA INSTALACIÓN
            # (`BASA_ENTITY_REGION`) como fallback retrocompatible.
            region = policy.resolve_region(
                pii_guardian.config if pii_guardian else None,
                default=os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION))

            # Mask custom names
            for idx, name in enumerate(custom_names):
                if not name.strip():
                    continue
                escaped_name = re.escape(name.strip())
                pattern = re.compile(rf"\b{escaped_name}\b", re.IGNORECASE)
                matches = pattern.findall(processed_prompt)
                if matches:
                    if action == "BLOCK":
                        blocked = True
                        block_reason = f"Seguridad: Se bloqueó la petición debido a la presencia de datos médicos/personales prohibidos ({name})."
                        triggers.append({
                            "guardian": pii_guardian.name if pii_guardian else "PII Guard",
                            "action": "BLOCK",
                            "detail": f"Nombre personalizado bloqueado: {name}"
                        })
                        break
                    elif action == "MASK":
                        placeholder = f"<PERSON_{idx+1}>"
                        for match in set(matches):
                            placeholder_map[placeholder] = match
                            entities_detected.append({
                                "type": "PERSON",
                                "entity": match
                            })
                        processed_prompt = pattern.sub(placeholder, processed_prompt)
                        triggers.append({
                            "guardian": pii_guardian.name if pii_guardian else "PII Guard",
                            "action": "MASK",
                            "detail": f"Enmascarado nombre personalizado: {name}"
                        })
            
            if blocked:
                return {
                    "prompt": processed_prompt,
                    "model": routed_model,
                    "blocked": True,
                    "block_reason": block_reason,
                    "placeholder_map": placeholder_map,
                    "entities_detected": entities_detected,
                    "triggers": triggers
                }
            
            # General Presidio scan — spec 016 T028/T029 (FR-012): prefiere el motor NLP
            # real (mismo sidecar que usa el firewall) si está configurado; degrada al
            # regex de dev SOLO de forma VISIBLE (trigger registrado), nunca en silencio
            # (spec.md Assumptions: este camino es interno/playground, no tráfico de
            # producción — puede degradar visible, pero jamás ocultarlo).
            presidio_url = os.environ.get("NLP_ANALYZER_URL")
            if presidio_url:
                try:
                    raw_entities = await PresidioService.analyze_text_http(
                        processed_prompt, presidio_url, custom_names=custom_names,
                        region=region)
                except NlpUnavailableError:
                    triggers.append({
                        "guardian": pii_guardian.name if pii_guardian else "PII Guard",
                        "action": "DEGRADED",
                        "detail": "Motor de detección NLP no disponible — degradado a regex "
                                  "de dev (SOLO panel/playground, nunca en el firewall real).",
                    })
                    # issue #63: el trigger es EFÍMERO (vive en la respuesta de este prompt y
                    # se lo lleva el próximo). Que la degradación se vea en la pantalla no es
                    # lo mismo que quede registrada: sin esta marca, un operador que revisa
                    # el estado media hora después no tiene forma de saber que el detector
                    # real estuvo caído. La marca es durable y la publica `GET /health`.
                    record_nlp_degradation(reason="playground/process_prompt")
                    raw_entities = await PresidioService.analyze_text(
                        processed_prompt, region=region)
            else:
                # issue #63: sin `NLP_ANALYZER_URL` el playground SIEMPRE corrió con el regex
                # de dev, y hasta acá no lo decía en ningún lado — la pantalla mostraba un
                # enmascarado exitoso sin distinguir con qué detector. No es una avería (es
                # el modo de desarrollo, Constraint SC-2), pero tampoco puede ser invisible:
                # la diferencia de cobertura es real y la ve el mismo humano que después
                # decide si el producto "detecta bien". Sin marca durable a propósito: no hay
                # degradación de un servicio configurado, hay una instalación sin motor NLP.
                triggers.append({
                    "guardian": pii_guardian.name if pii_guardian else "PII Guard",
                    "action": "DEGRADED",
                    "detail": "Detección NLP no configurada en esta instalación — se usa la "
                              "detección local por patrones (modo desarrollo, cobertura "
                              "menor). No usar con datos reales de pacientes.",
                })
                raw_entities = await PresidioService.analyze_text(processed_prompt, region=region)
            filtered_entities = [e for e in raw_entities if e["entity_type"] in entities_to_scan]
            
            if filtered_entities:
                if action == "BLOCK":
                    blocked = True
                    blocked_types = list(set([e["entity_type"] for e in filtered_entities]))
                    block_reason = f"Seguridad: Se bloqueó la petición debido a la presencia de datos médicos/personales prohibidos ({', '.join(blocked_types)})."
                    triggers.append({
                        "guardian": pii_guardian.name if pii_guardian else "PII Guard",
                        "action": "BLOCK",
                        "detail": f"Entidades bloqueadas: {', '.join(blocked_types)}"
                    })
                elif action == "MASK":
                    masked_text, p_map, d_entities = PresidioService.mask_text(processed_prompt, filtered_entities)
                    processed_prompt = masked_text
                    placeholder_map.update(p_map)
                    entities_detected.extend(d_entities)
                    if d_entities:
                        triggers.append({
                            "guardian": pii_guardian.name if pii_guardian else "PII Guard",
                            "action": "MASK",
                            "detail": f"Enmascarado: {', '.join([e['type'] for e in d_entities])}"
                        })

        if blocked:
            return {
                "prompt": processed_prompt,
                "model": routed_model,
                "blocked": True,
                "block_reason": block_reason,
                "placeholder_map": placeholder_map,
                "entities_detected": entities_detected,
                "triggers": triggers
            }

        # 4-6. Engine-backed guardrails (prompt injection, content moderation, bedrock, etc.)
        # These are executed by the AI engine on each request via the `guardrails` parameter
        # passed in chat.py. No local simulation needed — engine handles the blocking.
        # We only record which engine-backed guardrails are configured so they appear in the UI.
        engine_guardians = [
            g for g in guardians
            if g.is_active and getattr(g, "engine_guardrail_name", None)
        ]
        if engine_guardians:
            triggers.append({
                "guardian": "Motor de IA",
                "action": "DELEGATED",
                "detail": f"Guardianes activos en motor: {', '.join(g.engine_guardrail_name for g in engine_guardians)}"
            })

        return {
            "prompt": processed_prompt,
            "model": routed_model,
            "blocked": False,
            "block_reason": "",
            "placeholder_map": placeholder_map,
            "entities_detected": entities_detected,
            "triggers": triggers
        }
