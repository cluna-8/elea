# Análisis — Transferencias de datos personales a proveedores de IA en América (normativa a octubre de 2026)

**Tipo**: spike de investigación. No abre spec ni numeración, no toca código de producto. **Fecha**: 6-oct-2026.
**Rama**: `cluna-8/spike-transferencias-america`. **Contexto de producto**: spec 057
(`origin/057-porte-sentinel-068-redireccion-modelos`, `specs/057-porte-sentinel-068-redireccion-modelos/spec.md`
@ `29311ef`), FR-028 a FR-032 (`spec.md:576-608`): cada destino registra su jurisdicción de inferencia; los
destinos de proveedores sin garantías equivalentes (DeepSeek oficial) quedan bloqueados por defecto; «mi región» en la
línea América es el continente completo (lista editable `AMERICAS`); sin postura explícita, fuera de la región rige
enmascarado forzado o rechazo; vía OpenRouter, cero retención. La base legal de cada transferencia «la cubre Elea por
fuera del sistema» (`spec.md:795-797`).

> **Esto NO es asesoramiento legal.** Es una lectura técnica de normas y resoluciones publicadas, hecha por un agente de
> ingeniería para informar una decisión de producto. Todo lo marcado **[no verificado]** y toda la §4 (recomendación) tiene
> que confirmarlo un abogado de cada jurisdicción antes de venderse como «cumplimiento». Las secciones «Qué tiene que
> confirmar un abogado» (al final de §1 y en §6) listan los puntos más sensibles.

**Convención de marcas** (la del repo, como en `specs/DIAGNOSTICO-CI-main-2026-10.md:8-10`):
**[verificado]** = abrí el texto de la fuente oficial citada (ley, boletín, resolución, regulador) en esta sesión y vi lo que
afirmo; el enlace y la fecha de la norma van al lado. **[no verificado]** = sale de una fuente secundaria (estudios de
abogados, prensa), de un resumen que no pude contrastar, o es **interpretación** mía; se dice cuál. Las citas textuales son
cortas. Varias páginas oficiales fallaron con la herramienta de lectura y se descargaron con `curl` para leer el texto
íntegro; en esos casos «[verificado]» es sobre el texto descargado, no sobre un resumen.

**Marco**: la línea América es el perfil Argentina (Ley 25.326/AAIP) extendido; **GDPR y EU AI Act no rigen
acá** (AGENTS.md del repo). La UE aparece solo como *destino* posible de un proveedor de IA y como referencia de
adecuación en las leyes de América, no como ley aplicable a Elea.

---

## 0. Resumen ejecutivo

1. **Ninguna de las ocho jurisdicciones trata «América» como una zona de libre circulación.** La lista `AMERICAS`
   (FR-030) es una comodidad de producto, no una equivalencia jurídica: **EE. UU. no está en la lista de países adecuados
   de Argentina ni de Brasil [verificado]**; sí está en la de Colombia [verificado] y, condicionado al Marco de Privacidad
   de Datos (DPF), en la de Uruguay [verificado]. La **UE sí es adecuada** para AR, BR (desde 26-ene-2026), CO y UY
   [verificado]. China no es adecuada en ninguna [verificado donde hay lista; Perú y Chile, ver §1].
2. **Enmascarar no equivale a anonimizar.** El enmascarado de la pasarela es reversible por diseño (los valores «vuelven
   restaurados en la respuesta», `spec.md:278-280`): es **seudonimización**. En todas las leyes revisadas, el dato
   seudonimizado sigue siendo dato personal para quien tiene la clave (Elea); el enmascarado reduce riesgo y ayuda a
   cumplir minimización/seguridad, **pero no sustituye la base legal ni el mecanismo de transferencia** (§2).
3. **El riesgo de un proveedor chino no está en el modelo sino en la API de primera mano.** La política de DeepSeek
   almacena en la RPC, retiene «mientras sea necesario», permite usar los *inputs* para entrenar y se rige por la ley
   china [verificado]. Los mismos pesos abiertos alojados por un tercero en EE. UU. (Bedrock, Fireworks, Groq…) no mandan
   datos al desarrollador [verificado en la doc de esos alojadores], pero **conservan los riesgos del propio modelo**
   (censura, susceptibilidad a instrucciones maliciosas) [verificado, NIST CAISI] (§3).
4. **Recomendación de default para Eleia** (detalle en §4): (a) **sí** bloquear por defecto las APIs de primera mano de
   entidades de la RPC, criterio por *entidad e inferencia*, no por dominio; (b) fuera de `AMERICAS`, **enmascarado
   forzado con analizador fail-closed** (no «permitido», no «rechazar» a secas; rechazar solo para destinos de
   jurisdicción de preocupación); (c) Elea firma/registra por fuera del sistema: contrato de encargo con cada proveedor
   (sin entrenamiento, retención acotada, subencargados), el instrumento de transferencia de cada país (cláusulas AAIP,
   Anexo II ANPD, etc.), registros (RNBD AR/CO, URCDP UY, RNPDP PE), evaluación de impacto y aviso al titular.
5. **Hechos que cambian el calendario**: Chile entra en vigor el **1-dic-2026** (Ley 21.719), sin Agencia operativa ni
   lista de países/cláusulas todavía y con un proyecto de postergación a dic-2027 en trámite; Argentina firmó el 5-feb-2026
   un compromiso con EE. UU. de reconocerlo como adecuado, **sin acto de la AAIP** que lo implemente a la fecha;
   México reemplazó su ley (DOF 20-mar-2025) y cambió de autoridad; Perú tiene reglamento nuevo (DS 016-2024-JUS).

---

## 1. Tabla por país

### 1.0 Matriz de una mirada (destino del proveedor de IA)

Elea, o el cliente, envía datos personales a un proveedor de IA ubicado en…

| País (ley / autoridad) | **EE. UU.** | **UE** | **China** | Base principal |
|---|---|---|---|---|
| **Argentina** — Ley 25.326 / AAIP | No adecuado [V]; hay compromiso político (ARTI) sin acto AAIP [V el texto, NV la entrada en vigor] → cláusulas o consentimiento | **Adecuado** [V] | No adecuado [V] → cláusulas o consentimiento | Adecuación; cláusulas modelo (Disp. 60/2016, Res. 198/2023); consentimiento expreso (Dto. 1558 art. 12) |
| **Brasil** — LGPD / ANPD | No adecuado [V] → Anexo II (cláusulas-padrão) + base art. 7/11 | **Adecuado** (Res. CD/ANPD 32/2026) [V] | No adecuado [V] → Anexo II | Adecuación; cláusulas-padrão sin alterar; consentimiento específico y destacado |
| **Colombia** — Ley 1581 / SIC | **Adecuado** (CE 005/2017 num. 3.2) [V] | **Adecuado** [V] | **No** está en la lista [V] → excepciones art. 26 o declaración de conformidad | Lista de la SIC; excepciones del art. 26; contrato de transmisión (Dto. 1377 art. 25) |
| **México** — LFPDPPP (DOF 20-mar-2025) / Sec. Anticorrupción y Buen Gobierno | Sin régimen de adecuación [V] | Ídem | Ídem | Encargo con contrato; transferencia con aviso de privacidad y consentimiento o excepción (arts. 35-36) |
| **Chile** — Ley 21.719 / Agencia (vigente desde 1-dic-2026) | Sin lista (la Agencia no la ha publicado) [V] | Sin lista (aún) [V] | Sin lista [V] | Adecuación (por determinar), cláusulas/NCV/certificación (art. 27), excepciones |
| **Perú** — Ley 29733 + DS 016-2024-JUS / DGTAIPD | No encontré lista de adecuados [NV] → garantías (art. 18.2) + comunicar el flujo (art. 21) | Ídem [NV] | Ídem [NV] | Nivel adecuado o garantías; consentimiento; comunicación obligatoria a la autoridad |
| **Uruguay** — Ley 18.331 / URCDP | Adecuado **solo** para entidades del listado DPF + declaración de extensión (Res. 63/023, 70/023) [V] | **Adecuado** (Res. 23/021) [V] | No adecuado [V] → art. 23 o autorización URCDP con cláusulas | Adecuación; cláusulas (Res. 41/021, 8/026); consentimiento inequívoco; autorización |
| **EE. UU.** (como país de origen de la regla) — sin ley federal general | No restringe exportar datos de no residentes [NV exhaustivo]; DOJ 28 CFR 202 solo protege datos de **personas de EE. UU.** [V] | n/a | **Prohíbe/restringe** dar acceso a datos masivos de personas de EE. UU. a entidades de países de preocupación (China) [V] | Reglas de seguridad nacional, no de adecuación |

[V] = verificado, [NV] = no verificado. Detalle y fuentes en las subsecciones.

> **Distinción que rige casi todo el análisis: transferencia vs. encargo.** Un proveedor de IA que procesa por cuenta de
> Elea es, en la mayoría de las leyes, *encargado/operador*, no tercero. La consecuencia cambia por país: en **Colombia**,
> una *transmisión* a un encargado con contrato no requiere consentimiento (Dto. 1377/2013 art. 24 num. 2) [V; vigencia de
> la compilación a confirmar]; en **México**, enviar a un encargado no es «transferencia» por definición
> (art. 2 XX de la ley nueva) [V]; en **Brasil**, la transferencia a un *operador* en el exterior **sí** es transferencia
> internacional y exige mecanismo (Res. 19/2024, Anexo I arts. 3 y 5) [V]; en **Argentina**, el modelo de cláusulas de
> *prestación de servicios* (Disp. 60/2016, Anexo II) existe justamente para el importador-encargado (art. 25 de la ley)
> [V]; en **Chile** y **Uruguay** el régimen de transferencia se aplica igual. Elea debe fijar qué rol ocupa (ver D4, §5).

---

### 1.1 Argentina

| Aspecto | Contenido |
|---|---|
| **Regla** | Ley 25.326 art. 12.1: «Es prohibida la transferencia de datos personales de cualquier tipo con países u organismos internacionales o supranacionales, que no propocionen niveles de protección adecuados.» Excepciones (art. 12.2): colaboración judicial, datos médicos, transferencias bancarias/bursátiles, tratados, inteligencia contra crimen organizado. [V] [infoleg texto actualizado: https://servicios.infoleg.gob.ar/infolegInternet/anexos/60000-64999/64790/texact.htm] |
| **Consentimiento y cláusulas** | Dto. 1558/2001 art. 12: la prohibición «no rige cuando el titular de los datos hubiera consentido expresamente la cesión»; un nivel adecuado puede derivar «del amparo que establezcan las cláusulas contractuales». [V: https://servicios.infoleg.gob.ar/infolegInternet/anexos/70000-74999/70368/texact.htm]. *Nota: la spec 057 (`spec.md:795-797`) atribuye «cláusulas o consentimiento» al art. 12 de la ley; en rigor el art. 12 de la ley es la prohibición y las vías salen del Decreto reglamentario y de la Disp. 60/2016.* |
| **UE / EE. UU. / China** | Lista de adecuados: UE y EEE, Reino Unido, Suiza, Guernsey, Jersey, Isla de Man, Islas Feroe, Canadá (solo sector privado), Andorra, Nueva Zelanda, Uruguay, Israel (solo tratamiento automatizado) — Disp. DNPDP 60-E/2016 art. 3 sustituido por Res. AAIP 34/2019. [V: https://www.argentina.gob.ar/normativa/nacional/norma-267922/actualizacion, https://www.argentina.gob.ar/aaip/datospersonales/transferencias-internacionales]. **UE: adecuada. EE. UU. y China: no figuran.** |
| **EE. UU. — novedad** | Acuerdo de Comercio e Inversión Recíprocos EE. UU.–Argentina (ARTI), firmado el **5-feb-2026**, Anexo III §2 párr. 1: Argentina «shall provide certainty regarding the ability to move personal data out of its territory to the United States including by recognizing the United States as a country or jurisdiction that provides adequate data protection under Argentina's law». Entra en vigor 60 días después de que las partes notifiquen cumplidos los trámites legales (art. 6.7). [V el texto: https://ustr.gov/sites/default/files/files/Press/Releases/2026/US%20Argentina%20ARTI%20English%20Final%20February%202026.pdf]. **No encontré acto de la AAIP que lo reconozca ni la entrada en vigor del ARTI** (pedido de informes de Diputados lo trata como «compromiso públicamente anunciado»: https://rest.hcdn.gob.ar/web/tramites-parlamentarios/render/adjunto/69b17431db5ad.pdf) [V que el documento existe; la ausencia de acto es **[NV]** — verificar el Boletín Oficial antes de decidir]. Tratar EE. UU. como **no adecuado** hasta que haya acto. |
| **Bases para país no adecuado** | (1) cláusulas modelo: Disp. 60-E/2016 (cesión y prestación de servicios) y Res. AAIP 198/2023 (modelos RIPD responsable→responsable y responsable→encargado); usadas sin cambios no requieren autorización previa; contratos que difieran se presentan a la AAIP «dentro de los TREINTA (30) días corridos de su firma» (Disp. 60 art. 2) [V: https://servicios.infoleg.gob.ar/infolegInternet/anexos/265000-269999/267922/norma.htm, https://servicios.infoleg.gob.ar/infolegInternet/anexos/390000-394999/391538/norma.htm]; (2) consentimiento expreso (Dto. 1558 art. 12); (3) normas corporativas vinculantes (Res. 159/2018) [la página AAIP lo dice; la resolución no se abrió → NV]. Interés legítimo: **no existe como base de transferencia** en la ley. |
| **Obligaciones del responsable (Elea)** | Inscripción de la base en el RNBD si se destina a dar informes (art. 21) [V el texto; alcance exacto para bases corporativas **[NV]**]; consentimiento/cesión (art. 11); seguridad y confidencialidad (arts. 9-10); contrato con el prestador que fije que «sólo actúa siguiendo instrucciones» (Dto. art. 25); exigir al prestador no usar para otro fin ni ceder, y destruir al terminar (ley art. 25) [V]. No encontré obligación de DPO, de notificar brechas ni de EIPD en la ley/decreto [V búsqueda de texto]; la **Guía AAIP de IA responsable** (2024-2025, no vinculante) recomienda DPD, evaluación de impacto e informar al titular si hay transferencia internacional [V: https://www.argentina.gob.ar/sites/default/files/guia_ai-final-2025.pdf]. |
| **Qué hace el sistema vs. qué hace Elea** | *Sistema*: decide si el pedido sale, sale enmascarado o se rechaza según la postura (FR-026/027, `spec.md:568-575`); registra jurisdicción por destino (FR-028). *Elea (fuera del sistema)*: elegir el instrumento (cláusulas Disp. 60/Res. 198 o consentimiento), firmarlo con el proveedor, inscribir la base, informar al titular, presentar a la AAIP lo que se aparte del modelo. |
| **Sanciones** | Ley art. 31: apercibimiento, suspensión, multa de $1.000 a $100.000, clausura o cancelación [V]. Res. AAIP 126/2024 (B.O. 24-may-2024) gradúa: leve $1.000–$80.000; grave $80.001–$90.000; muy grave $90.001–$100.000, con acumulación hasta ×500 [V: https://www.argentina.gob.ar/normativa/nacional/resoluci%C3%B3n-126-2024-399750/actualizacion]. **«Transferir datos personales de cualquier tipo a países … que no proporcionen niveles de protección adecuados … sin haber cumplido los demás recaudos legales» es infracción muy grave** (Res. 126/2024, Anexo I, 3.g) [V]. Sanciones penales: ley art. 32 [V]. |
| **Reforma** | La Ley 25.326 sigue siendo el texto vigente. Proyecto 3397-D-2026 (16-jul-2026), reintroduce la reforma integral; «etapa temprana» [NV, secundaria: Allende & Brea]. |

### 1.2 Brasil

| Aspecto | Contenido |
|---|---|
| **Regla** | LGPD (Lei 13.709/2018) art. 33: la transferencia internacional solo se permite en casos tasados: I) país/organismo con grado de protección adecuado; II) el controlador ofrece y comprueba garantías mediante cláusulas específicas, **cláusulas-padrão contratuais**, normas corporativas globales o sellos/certificados/códigos; V) autorización de la ANPD; VIII) «consentimiento específico e em destaque … com informação prévia sobre o caráter internacional da operação»; IX) necesidad para ejecución de contrato/obligación legal/derechos (art. 7 II, V, VI). [V: https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm, texto compilado descargado con curl]. |
| **Reglamento** | Res. CD/ANPD 19/2024 (DOU 23-ago-2024): el controlador debe verificar que hay transferencia, que se aplica la LGPD y que existe **base legal (art. 7 u 11) y mecanismo válido** (Anexo I art. 4 y 9); con cláusulas-padrão, validez exige «adoção integral e sem alteração» del Anexo II (art. 16); plazo de adopción: 12 meses → **23-ago-2025, ya vencido** (art. 2 párr. único). La recolección directa por el agente extranjero no es transferencia (art. 6). [V: https://www.in.gov.br/en/web/dou/-/resolucao-cd/anpd-n-19-de-23-de-agosto-de-2024-580095396]. Un operador extranjero que recibe datos del exportador es «importador» y la operación es transferencia (arts. 3 y 5) [V]. |
| **UE / EE. UU. / China** | **Res. CD/ANPD 32/2026 (26-ene-2026, DOU 27-ene-2026): la UE (Estados miembros + Islandia, Liechtenstein, Noruega) es adecuada**; no aplica a fines exclusivos de seguridad pública/defensa; reevaluación en 4 años [V: https://www.in.gov.br/web/dou/-/resolucao-n-32-de-26-de-janeiro-de-2026-683334547]. ANPD declara que solo la UE ha sido reconocida [V: https://www.gov.br/anpd/pt-br/assuntos/assuntos-internacionais/transferencia-internacional-de-dados]. **EE. UU. y China: no adecuados → Anexo II + base legal.** |
| **Obligaciones del responsable (Elea)** | Verificar tipo de operación y mecanismo (Anexo I art. 4); registro de operaciones (art. 37); RIPD cuando la ANPD lo pida (art. 38); encargado (DPO, art. 41); instrucciones al operador (art. 39), responsabilidad solidaria del operador si incumple (art. 42 §1 I); minimización «mínimo necessário» en la transferencia (Anexo I art. 9 párr. único); notificación de incidentes a ANPD y titulares en **3 días hábiles** (Res. CD/ANPD 15/2024; cláusula 16.1 del Anexo II) [V]. Las cláusulas-padrão se rigen por derecho brasileño y tribunales de Brasil (cl. 24.1) y limitan los *onward transfers* a los autorizados (cl. 3 y 18) [V]. |
| **Qué hace el sistema vs. Elea** | *Sistema*: enmascarado forzado y bloqueo ayudan a la minimización (art. 9 párr. único). *Elea*: firmar el Anexo II **sin alterar** con cada proveedor importador (muchos proveedores de IA no lo ofrecen: verificar), documentar la base art. 7/11, ROPA, RIPD, DPO, plan de incidentes. |
| **Sanciones** | LGPD art. 52 II: multa simple de hasta 2% del faturamento en Brasil, máx. R$ 50.000.000 por infracción; además advertencia, multa diaria, publicización, bloqueo/eliminación, suspensión parcial del banco de datos hasta 6 meses, prohibición parcial/total [V]. Res. CD/ANPD 4/2023 art. 15 (cálculo) [V: https://dspace.mj.gov.br/bitstream/1/9179/2/RES_ANPD_2023_4.html]. |
| **Cambios al texto** | Lei 15.352/2026 y Lei 15.452/2026 modificaron disposiciones de la LGPD sobre la ANPD (ahora «Agência Nacional de Proteção de Dados»); no se revisó el alcance de todos los cambios **[NV]**. |
| **IA** | ANPD «Radar Tecnológico nº 3 — IA generativa» (nov-2024): señala riesgo de reuso de *prompts*; no trata transferencia internacional [V]. PL 2338/2023 (marco de IA): aprobado por el Senado, en la Cámara; **no es ley** [V la tramitación Senado; el calendario posterior **[NV]**]. |

### 1.3 Colombia

| Aspecto | Contenido |
|---|---|
| **Regla** | Ley 1581/2012 art. 26: «Se prohíbe la transferencia de datos personales de cualquier tipo a países que no proporcionen niveles adecuados de protección de datos.» Excepciones: autorización «expresa e inequívoca»; datos médicos; transferencias bancarias/bursátiles; tratados; ejecución de contrato con el titular (con autorización); interés público/defensa judicial. Parág. 1: la SIC emite la **declaración de conformidad**. [V: http://www.secretariasenado.gov.co/senado/basedoc/ley_1581_2012.html, «última actualización 30-sep-2026»]. |
| **Lista de adecuados** | Circular Externa SIC 005/2017, Título V, Cap. 3, num. 3.2: incluye los 27 Estados de la UE, Reino Unido, Noruega, Islandia, Corea, Costa Rica, Serbia, México, Perú y **«Estados Unidos de América»**, más los declarados adecuados por la Comisión Europea; **China no figura** [V: https://www.cancilleria.gov.co/sites/default/files/Normograma/docs/circular_superindustria_0005_2017.htm]. Borrador de la SIC (publicado 26-may-2026; comentarios hasta 10-jun-2026) mantiene EE. UU. y suma Australia, Brasil, Ecuador, Japón, Kenia, Panamá y Sudáfrica; **es proyecto, no norma** [V: https://sedeelectronica.sic.gov.co/transparencia/normativa/proyecto-de-resolucion-por-la-cual-se-modifica-el-titulo-v-de-la-circular-unica-de-la-superintendencia-de-industria-y]; si se expidió después de junio de 2026 **[NV]**. |
| **Bases para China** | Excepciones del art. 26 (autorización expresa e inequívoca, etc.) o declaración de conformidad (CE 005/2017 num. 3.3: contrato con el destinatario que garantice los principios + comunicación previa a la SIC). **Las cláusulas modelo de la Red Iberoamericana (CE SIC 003/2025, 19-dic-2025) «no implican el levantamiento ni la inaplicación» de la prohibición del art. 26** [V el texto OCR: https://sedeelectronica.sic.gov.co/transparencia/normativa/circular-externa-no-003-del-19-de-diciembre-de-2025] → para China, las cláusulas solas no alcanzan. |
| **Transmisión a encargado** | Dto. 1377/2013 art. 3 num. 5 y art. 24 num. 2: la transmisión internacional a un encargado «no requerirá ser informada al Titular ni contar con su consentimiento cuando exista un contrato en los términos del artículo 25» [V: https://normograma.mintic.gov.co/mintic/compilacion/docs/decreto_1377_2013.htm]. Vigencia tras la compilación en el Dto. 1074/2015 (el art. 25 aparece «no compilado»): **[NV]** — confirmar. CE SIC 002/2025 (7-oct-2025) recuerda que quien transfiera o transmita debe validar que el destino sea adecuado o que aplique una excepción [V: https://normograma.mintic.gov.co/mintic/compilacion/docs/circular_superindustria_0002_2025.htm]. |
| **Obligaciones del responsable (Elea)** | Contrato de transmisión (Dto. 1377 art. 25); RNBD (art. 25 ley); responsabilidad demostrada (Dto. 1377 arts. 26-27); cumplir lineamientos de IA: la CE 002/2024 aplica la ley a todo tratamiento «para desarrollar, probar y monitorear Sistemas de Inteligencia Artificial», exige ponderación y estudio de impacto de privacidad si el riesgo es alto, y la CE 002/2025 (inst. 3.3) promueve «anonimización o seudonimización» [V: https://normograma.mintic.gov.co/mintic/compilacion/docs/circular_superindustria_0002_2024.htm]. |
| **Qué hace el sistema vs. Elea** | *Sistema*: enmascarado (la SIC lo promueve como buena práctica). *Elea*: contrato de transmisión, RNBD, estudio de impacto, declaración de conformidad solo si el destino no es adecuado (p. ej. China) y no hay excepción. |
| **Sanciones** | Ley 1581 art. 23: multas sucesivas hasta **2.000 SMMLV**; suspensión hasta 6 meses; cierre temporal; cierre inmediato y definitivo de la operación con datos sensibles [V]. |
| **Reforma** | No encontré reforma aprobada; Proyecto de Ley 247/2025 Cámara (acumulado con 214/2025) en trámite: foro de la SIC del 12-nov-2025 [V: https://sedeelectronica.sic.gov.co/noticias/la-sic-lidera-discusion-sobre-la-reforma-la-ley-de-proteccion-de-datos-personales-en-colombia]; cifras de multa del proyecto **[NV]**. |

### 1.4 México

| Aspecto | Contenido |
|---|---|
| **Ley y autoridad** | Nueva **Ley Federal de Protección de Datos Personales en Posesión de los Particulares**, publicada en el DOF el **20-mar-2025**, en vigor al día siguiente (Transitorio Primero); abroga la de 2010. Autoridad: **Secretaría Anticorrupción y Buen Gobierno** (art. 2 XV); el INAI se extinguió. Última reforma DOF 14-nov-2025 (solo art. 4) [V: https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf]. |
| **Transferencia / encargo** | Art. 2 XX: transferencia = «Toda comunicación de datos personales dentro o fuera del territorio mexicano, realizada a persona distinta de la titular, del responsable o de la persona encargada del tratamiento» (no cubre al encargado). Art. 35: al transferir a terceros nacionales o extranjeros, aviso de privacidad con cláusula de aceptación; el receptor asume las mismas obligaciones. Art. 36: supuestos sin consentimiento (ley/tratado, salud, grupo corporativo, contrato, interés público/justicia, defensa de un derecho, relación jurídica). **No hay régimen de adecuación ni lista de países** [V]. |
| **Remisión** | La ley nueva **no define «remisión»**. El Reglamento de 2011 (DOF 21-dic-2011) sí: art. 2 IX y art. 53 — las remisiones (responsable→encargado) nacionales e internacionales «no requerirán ser informadas al titular ni contar con su consentimiento»; art. 51 exige contrato [V: https://dof.gob.mx/nota_detalle.php?codigo=5226005&fecha=21%2F12%2F2011]. **Si el Reglamento de 2011 sigue vigente bajo la ley nueva: [NV]** (la ley nueva no declara su vigencia ni derogación en los transitorios leídos; prensa dice que la Secretaría anunció en ene-2026 una reforma reglamentaria, **[NV]**). |
| **UE / EE. UU. / China** | Sin distinción por país: lo que importa es si el proveedor es encargado (contrato) o tercero (aviso + consentimiento/excepción). |
| **Obligaciones del responsable (Elea)** | Aviso de privacidad (con cláusula de transferencias si aplica); contrato con el encargado; consentimiento expreso (y por escrito para sensibles, art. 8); art. 26 II: oposición a tratamiento automatizado. Ninguna otra disposición menciona «inteligencia artificial» ni «algoritmo» [V búsqueda de texto]. |
| **Sanciones** | Art. 59: multas de 100 a 160.000 UMA (fracciones II-VII del art. 58) y de 200 a 320.000 UMA (VIII-XVIII), adicional por reiteración, duplicables si hay datos sensibles; art. 58 XII-XIII: transferir fuera de los casos permitidos / sin consentimiento expreso; delitos arts. 62-64 (prisión de 3 meses a 5 años, duplicada para sensibles) [V]. Valor de la UMA 2026 **[NV]**. |

### 1.5 Chile

| Aspecto | Contenido |
|---|---|
| **Ley y vigencia** | **Ley 21.719** (promulgada 25-nov-2024; **D. Oficial 13-dic-2024**), crea la Agencia de Protección de Datos Personales y reforma la Ley 19.628. Artículo 1º transitorio: las modificaciones entran en vigencia «el día primero del mes vigésimo cuarto posterior a la publicación» → **1-dic-2026** (cómputo mío sobre texto oficial) [V: https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma=1209272]. **Postergación**: el Ejecutivo ingresó el 1-sep-2026 el Boletín 18.623-07 (vigencia al **1-dic-2027**, Consejo de 3 a 5 miembros), urgencia «Suma», última actuación vista 22-sep-2026, en tramitación [V: https://tramitacion.senado.cl/wspublico/tramitacion.php?boletin=18623, https://www.economia.gob.cl/2026/09/01/gobierno-propone-ampliar-plazo-para-implementar-nueva-ley-de-proteccion-de-datos-y-institucionalidad.htm]; si se aprobó después: **[NV]**. La Agencia **no tiene Consejo** (el Senado desestimó la propuesta de consejeros el 20-may-2026) [V: https://www.senado.cl/comunicaciones/noticias/desestiman-propuesta-de-consejeros-para-la-agencia-de-proteccion-de-datos]. |
| **Hoy (hasta la vigencia)** | La Ley 19.628 vigente **no contiene regla de transferencia internacional** (solo menciona transmisiones a organizaciones internacionales por tratados, art. 5) [V: https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma=141599]. |
| **Regla nueva** | Arts. 27-29: es lícita la transferencia (cumpliendo los requisitos de licitud del tratamiento) si el destinatario está en un país con **nivel adecuado** determinado por la Agencia; o hay **cláusulas contractuales, normas corporativas vinculantes u otros instrumentos** con garantías adecuadas; o **modelo de cumplimiento/certificación**; excepciones para transferencias específicas y no habituales: **consentimiento expreso**, contrato, urgencia, etc. La carga de acreditar la licitud es del responsable (art. 28). La Agencia fiscaliza y puede suspender el envío (art. 29). [V]. |
| **UE / EE. UU. / China** | **No hay lista de adecuados ni cláusulas modelo de la Agencia todavía** (la Agencia no está operativa) [V]. En la práctica, vía art. 27 b) con cláusulas propias y garantías exigibles (lectura mía **[NV]**). |
| **Obligaciones del responsable (Elea)** | Encargado: contrato con objeto, duración, finalidad, tipo de datos; sin subencargados sin autorización específica y escrita (art. 15 bis) [V]; EIPD para tratamientos de alto riesgo/gran escala (art. 15 ter) [V]; derecho a no ser objeto de decisiones automatizadas (art. 8 bis) [V]; seguridad y notificación de vulneraciones. |
| **Sanciones** | Transferencia contraria a la ley: **grave** (art. 34 ter m) — hasta 10.000 UTM; **gravísima si es a sabiendas** (art. 34 quáter h) — hasta 20.000 UTM; reincidentes no menores: hasta 2% o 4% de ingresos anuales (art. 35); suspensión hasta 30 días por gravísimas reiteradas (art. 38) [V]. Durante 12 meses desde la vigencia, a empresas de menor tamaño la Agencia puede aplicar solo amonestación (art. 6 transitorio) [V]. |

### 1.6 Perú

| Aspecto | Contenido |
|---|---|
| **Normas** | Ley 29733 (2011) [V, OCR de https://www.leyes.congreso.gob.pe/Documentos/Leyes/29733.pdf]; **Reglamento DS 016-2024-JUS** (firmado 29-nov-2024; vigencia a los 120 días de su publicación, ≈ fines de mar-2025 por cómputo; deroga el DS 003-2013-JUS) [V: https://www.smv.gob.pe/Uploads/DS016_2024_JUS.pdf]; fecha exacta de publicación **[NV]**. Autoridad: DGTAIPD del MINJUS (Ley art. 32; Reglamento art. 2 num. 9) [V]. |
| **Flujo transfronterizo** | Ley art. 15: solo si el país destinatario mantiene niveles adecuados; si no, el emisor «debe garantizar» el cumplimiento de la ley; excepciones (tratados, relación contractual con el titular, bancarias, salud, consentimiento «previo, informado, expreso e inequívoco», etc.). Reglamento arts. 18-21: el exportador otorga garantías (cláusulas modelo u otros instrumentos; la DGTAIPD emite modelos) y **«en cualquier caso, el flujo transfronterizo debe ponerse en conocimiento de la [DGTAIPD]… Dicha comunicación es inscrita en el Registro Nacional de Protección de Datos Personales»** (art. 21) [V]. |
| **UE / EE. UU. / China** | **No encontré lista ni resolución de países adecuados** (art. 19 la prevé) **[NV]**. RD 074-2022-JUS/DGTAIPD adoptó cláusulas modelo de la Red Iberoamericana (la cita la SIC colombiana) [V que la cita; texto de la RD **[NV]**]. |
| **Tercerización tecnológica** | Reglamento arts. 28-29: tratamiento por medios tecnológicos tercerizados; el responsable debe informar subcontrataciones, evitar condiciones que cedan la titularidad al prestador, garantizar confidencialidad/integridad/disponibilidad, control y responsabilidad, y destrucción al terminar [V]. Es el régimen más cercano a una API de modelo (lectura mía **[NV]**). |
| **Sanciones** | Ley art. 39: leves 0,5-5 UIT; graves >5-50 UIT; muy graves >50-100 UIT; tope 10% de ingresos brutos anuales [V]. No comunicar el flujo transfronterizo: infracción **leve** (Reglamento art. 132 num. 8) [V]. Valor UIT 2026 **[NV]**. |

### 1.7 Uruguay

| Aspecto | Contenido |
|---|---|
| **Regla** | Ley 18.331 art. 23: «Se prohíbe la transferencia de datos personales de cualquier tipo con países u organismos internacionales que no proporcionen niveles de protección adecuados…». Supuestos admitidos: consentimiento «inequívoco», contrato con el interesado o en su interés, interés público/defensa de derecho, interés vital, registro público; la URCDP puede autorizar a un país no adecuado con «garantías suficientes… cláusulas contractuales apropiadas». [V: https://www.impo.com.uy/bases/leyes/18331-2008]. Aplicación extraterritorial: Ley 19.670 art. 37 (oferta de bienes/servicios a habitantes de Uruguay) [V]. |
| **Lista de adecuados** | Res. URCDP **23/021** (8-jun-2021): UE y EEE, Andorra, Argentina, Canadá (sector privado), Guernsey, Isla de Man, Feroe, Israel, Japón, Jersey, Nueva Zelanda, Reino Unido, Suiza; **EE. UU. excluido** [V: https://www.gub.uy/unidad-reguladora-control-datos-personales/institucional/normativa/resolucion-n-23021]. Res. **63/023** (nov-2023): suma Corea del Sur y **las transferencias a organizaciones del listado del Marco de Privacidad de Datos (DPF)** [V: .../resolucion-n-63023]. Res. **70/023** (5-dic-2023): para EE. UU. exige que la importadora declare haber **extendido las salvaguardas del DPF a los datos transferidos desde Uruguay**; sin esa declaración, solo cláusulas autorizadas por la URCDP u otro fundamento legal; inscripción previa de la base y deber de informar al titular destino y rol del importador [V: .../resolucion-n-70023]. **China: no figura** [V]. |
| **Cláusulas** | Res. 41/021 (contenido mínimo de cláusulas); Res. **8/026** (17-abr-2026): habilita los módulos de cláusulas contractuales tipo del Comité del Convenio 108+ (resp.→resp., resp.→enc., enc.→enc.), «con las adaptaciones» necesarias, sin excluir la valoración/autorización de la URCDP [V parcial: el texto que vi se corta en esa frase] [V: .../resolucion-n-8026-sobre-clausulas-contractuales]. |
| **Obligaciones del responsable (Elea)** | Inscribir la base en el Registro **antes** de operar (art. 28-29; Res. 70/023); responsabilidad proactiva, privacidad por diseño/por defecto y EIPD (art. 12 según Ley 19.670 art. 39); **EIPD previa para transferencias a países sin nivel adecuado** (Dto. 64/020 art. 6 f) y DPD si hay grandes volúmenes (>35.000 personas) (Dto. 64/020 art. 10); notificar brechas a la URCDP en **72 horas** (art. 4) [V: https://www.impo.com.uy/bases/decretos/64-2020]. La autorización de transferencia se solicita por el exportador con el contrato importador-exportador (Dto. 414/009 arts. 34-35) [V]. |
| **Sanciones** | Art. 35: observación, apercibimiento, multa hasta **500.000 UI**, suspensión de la base (5 días), clausura (vía judicial) [V]. |

### 1.8 Estados Unidos

No hay ley federal general de privacidad. Lo relevante para un cliente de América que usa proveedores de IA estadounidenses (y para
Elea si maneja datos de personas de EE. UU.):

| Aspecto | Contenido |
|---|---|
| **Regla federal de «países de preocupación»** | **DOJ, Data Security Program**, 28 CFR Parte 202 (EO 14117; regla final 90 FR 1636, 8-ene-2025; en vigor 8-abr-2025; corrección 90 FR 16466, 18-abr-2025). Prohíbe o restringe a *U.S. persons* dar acceso a datos sensibles masivos de **personas de EE. UU.** y a datos gubernamentales a **países de preocupación** (China —con Hong Kong y Macao según la FAQ 13—, Cuba, Irán, Corea del Norte, Rusia, Venezuela: §202.601) o *covered persons* (entidades organizadas o con sede en esos países o con ≥50% de propiedad: §202.211), mediante *data brokerage* (prohibida, §202.301) o contratos de proveedor/empleo/inversión (restringidos, §202.401). Umbrales (§202.205): genómicos >100 personas; otros ómicos, biométricos, geolocalización >1.000; salud, financieros >10.000; identificadores personales cubiertos >100.000. Obligaciones de diligencia, auditoría y programa de cumplimiento desde **6-oct-2025** (§202.1001; subparte J). [V eCFR https://www.ecfr.gov/current/title-28/part-202 y FR API; FAQ del DOJ 24-sep-2025 https://www.justice.gov/nsd/media/1415006/dl]. **Sin enmiendas a la Parte 202 después del 18-abr-2025** [V en eCFR/FR API]. |
| **¿Protege datos de latinoamericanos?** | **No, salvo que sean *U.S. persons***: ciudadanos o residentes permanentes de EE. UU. dondequiera que estén, o cualquier persona *en* EE. UU. (§202.256); una subsidiaria constituida fuera de EE. UU. es persona extranjera aunque sea 100% de una matriz estadounidense (§202.256 ej. 6) [V]. Para un empleado latinoamericano que está temporalmente en EE. UU., sí cuenta (ej. 1) [V]. Los datos «anonimizados, seudonimizados, de-identificados o cifrados» **igual cuentan** como datos masivos (§202.206) [V]. |
| **API de IA china / modelo chino alojado en EE. UU.** | Una API de proveedor con sede en China sería *covered person*; un contrato de nube/servicio que le dé acceso a datos masivos de personas de EE. UU. es un *vendor agreement* restringido (§202.258 incluye «cloud-computing services»); ejecutar pesos abiertos en infraestructura propia, sin acceso de un *covered person*, no es *covered data transaction* (§202.210). **Interpretación mía, no hay guía específica del DOJ sobre LLM [NV]**; confirmar con abogado de EE. UU. si Elea o un cliente maneja datos masivos de personas de EE. UU. La exención de telecomunicaciones **no** cubre servicios de nube (FAQ 77) [V]. |
| **PADFAA** (15 U.S.C. 9901) | Prohíbe a *data brokers* vender o dar acceso a datos sensibles de personas **residentes en EE. UU.** a adversarios extranjeros; FTC envió cartas de advertencia a 13 *data brokers* el 9-feb-2026; penal civil hasta $53.088 por violación [V: https://www.ftc.gov/news-events/news/press-releases/2026/02/ftc-reminds-data-brokers-their-obligations-comply-padfaa]. |
| **Leyes estatales** | Unos 20 estados con ley integral en 2026 (CA, CO, CT, DE, FL, IN, IA, KY, MD, MN, MT, NE, NH, NJ, OR, RI, TN, TX, UT, VA) — **[NV]**, fuentes secundarias (la lista oficial por estado no se abrió). Todas protegen a **residentes del estado**. California (texto oficial CPPA): «consumer» = residente de California (§1798.140(i)); «deidentified» exige medidas razonables, compromiso público de no reidentificar y obligación contractual a los receptores (§1798.140(m)); «service provider» exige contrato que prohíba vender, compartir, usar fuera del fin o combinar (§1798.140(ag)) [V: https://cppa.ca.gov/regulations/pdf/cppa_act.pdf, versión 15-jul-2024]. Regulaciones CPPA (ADMT, evaluaciones de riesgo, ciberseguridad) efectivas 1-ene-2026 [V]. **No encontré ley estatal ni federal que restrinja exportar datos de residentes de otros países hacia EE. UU. [NV, negativo no exhaustivo].** Prohibiciones a dispositivos gubernamentales (TX, NY, VA) sobre apps chinas: **[NV]**. |
| **Sanciones de referencia** | DSP/IEEPA civil: el mayor entre $368.136 (texto del CFR, §202.1301) o dos veces el valor de la transacción; Treasury ajustó IEEPA a $377.700 (FR 2025-00786, 15-ene-2025) → discrepancia **[V ambos]**; penal hasta $1.000.000 y 20 años [V]. CCPA: $2.663 por infracción y $7.988 intencional o de menores de 16 (ajuste vigente desde 1-ene-2025) [V: https://cppa.ca.gov/announcements/2024/20241217.html]. FTC §5(m): $53.088, sin ajuste en 2026 (FR 2026-18853) [V]. |
| **Contexto UE–EE. UU.** | DPF: decisión de adecuación del 10-jul-2023; el Tribunal General desestimó la acción *Latombe* (T-553/23) el 3-sep-2025 [V]; apelación C-703/25 P pendiente **[NV]**. Reconocimiento en América: Colombia lista EE. UU. (desde 2017, independiente del DPF) [V]; Uruguay reconoce el DPF [V]; Argentina y Brasil no [V]. |

### 1.9 Qué tiene que confirmar un abogado (de §1)

1. Si la **ARTI** (Argentina–EE. UU.) entró en vigor y si la AAIP emitió acto de adecuación (Boletín Oficial al día de uso).
2. En **Brasil**: qué proveedores de IA aceptan el Anexo II sin alterar, y el efecto de las leyes 15.352/2026 y 15.452/2026.
3. En **Colombia**: vigencia actual del Dto. 1377 art. 24 num. 2 y art. 25; si el Título V de la Circular Única ya fue modificado; si la SIC aplica el art. 26 a una *transmisión* a un encargado en país no adecuado (no hallé pronunciamiento).
4. En **México**: si el Reglamento de 2011 sigue aplicándose; si hay lineamientos nuevos de la Secretaría.
5. En **Chile**: la suerte del Boletín 18.623-07 (¿se posterga a dic-2027?) y qué hacer sin cláusulas modelo de la Agencia.
6. En **Perú**: si existe lista de países adecuados o modelos vigentes de la DGTAIPD, y el valor de la UIT 2026.
7. En **Uruguay**: si hubo actualizaciones de la lista posteriores a la Res. 63/023 y el texto completo de la Res. 8/026.
8. En **EE. UU.**: aplicabilidad de 28 CFR 202 a APIs de IA y a modelos de origen chino alojados por terceros.
9. El rol de Elea (responsable vs. encargado) en cada instalación (D4, §5).

---

## 2. El efecto del enmascarado: ¿siguen siendo datos personales?

### 2.1 Qué hace exactamente el enmascarado de la pasarela (hechos del producto)

- **Es reversible.** Con *fuera de región con enmascarado forzado*, «los datos personales detectados salen enmascarados y vuelven
  restaurados en la respuesta, incluidos resultados de herramientas y adjuntos analizables» (`spec.md:278-280`). Quien guarda
  la correspondencia valor→marcador es Elea (la pasarela). Esto es **seudonimización**, no anonimización.
- **Cubre lo que el analizador detecta**, no todo identificador posible: el set por defecto del perfil argentino es
  `PERSON, DNI, CUIL, EMAIL_ADDRESS, PHONE_NUMBER` (`backend/src/services/guardian_service.py:313`; `:38`), y el perfil `latam_ar`
  del analizador emite además `PASSPORT` y `CBU` (`specs/DIAGNOSTICO-CI-main-2026-10.md:261-264`). Nombres de organizaciones,
  direcciones, cargos, contexto («el gerente de la sucursal de X que despidió a …»), datos de salud en texto libre y combinaciones
  casi-identificadoras **pueden pasar sin enmascarar**. Que el analizador no detecte algo no lo vuelve anónimo.
- **Garantía de fail-closed**: con el analizador caído, el pedido a otra jurisdicción se bloquea (FR-027, `spec.md:571-575`); lo no
  analizable bloquea. Esto protege contra salidas sin enmascarar, no contra re-identificación por contexto.

### 2.2 Qué dice cada ley sobre anonimización vs. seudonimización

| País | Definición/criterio | ¿El seudonimizado/enmascarado reversible sigue siendo dato personal? |
|---|---|---|
| **Argentina** | Ley 25.326 art. 2: «Disociación de datos: todo tratamiento… de manera que la información obtenida no pueda asociarse a persona determinada o determinable»; dato personal = información de personas «determinadas o determinables» [V]. Art. 11.3.e: no hace falta consentimiento para ceder si se aplicó disociación «de modo que los titulares… sean inidentificables» [V]. No define seudonimización. | **Sí** (lectura mía: con una clave es «determinable») **[NV]**; solo la disociación efectiva saca el dato del régimen. La Guía AAIP de IA advierte de la «reidentificación de datos anónimos» [V]. |
| **Brasil** | LGPD art. 5 III: dado anonimizado = no identificable «considerando a utilização de meios técnicos razoáveis e disponíveis»; art. 12: no son dato personal «salvo quando o processo … for revertido, utilizando exclusivamente meios próprios, ou quando, com esforços razoáveis, puder ser revertido»; art. 13 §4: seudonimización = pérdida de la asociación directa o indirecta «senão pelo uso de informação adicional mantida separadamente pelo controlador em ambiente controlado e seguro» [V]. | **Sí, para el controlador que mantiene la clave** (el §4 del art. 13 describe un dato que sigue asociable). La ANPD, en su estudio técnico (nov-2023, no vinculante): con seudonimización «a identificação dos titulares… permanece possível a partir do acesso ao segredo» [V]. Ver §2.3 sobre el receptor. |
| **Colombia** | La ley no define anonimización ni seudonimización; dato personal = información «vinculada o que pueda asociarse» a personas determinadas o determinables (art. 3 c) [V]. La CE 002/2025 las trata como medidas de diseño, no como exclusión del régimen [V]. | **Sí** (inferencia: «puede asociarse») **[NV]**. |
| **México** | Ley nueva art. 2 IX: «Disociación: procedimiento mediante el cual los datos personales no pueden asociarse a la persona titular ni permitir, por su estructura, contenido o grado de desagregación, la identificación de la misma»; art. 9 III: sin consentimiento si hay disociación previa; no define anonimización ni seudonimización [V]. | **Sí** para lo reversible (no «no pueden asociarse») **[NV]**. |
| **Chile** | Ley 21.719 art. 2: **anonimización** = «procedimiento irreversible… Un dato anonimizado deja de ser un dato personal»; **seudonimización** = tratamiento tal que «ya no puedan atribuirse a un titular sin utilizar información adicional», que figura por separado y sujeta a medidas; dato identificable considera «todos los medios y factores objetivos que razonablemente se podrían usar» [V]. | **Sí** (la ley solo excluye al «anonimizado»; lectura mía) **[NV]**. |
| **Perú** | Ley 29733 art. 2: **anonimización** = impide la identificación; «el procedimiento es irreversible»; **disociación** = igual, pero «el procedimiento es reversible»; Reglamento art. 2 num. 4: identificable «a partir de la combinación de datos a través de medios que puedan ser razonablemente utilizados» [V]. | **Sí** para disociación/seudonimización reversible; solo la anonimización irreversible sale (lectura mía) **[NV]**. |
| **Uruguay** | Ley 18.331 art. 4 G): disociación = tratamiento tal que la información «no pueda vincularse a persona determinada o determinable»; art. 4 D) dato personal incluye personas **jurídicas** determinadas o determinables [V]. No define seudonimización. | **Sí** (sigue vinculable) **[NV]**. |
| **EE. UU.** | DOJ §202.206: los datos masivos cuentan «regardless of whether the data is anonymized, pseudonymized, de-identified, or encrypted» [V]. CCPA §1798.140(m) «deidentified» exige no poder inferir/vincular + compromiso público + contrato; «pseudonymize» = no atribuible sin información adicional separada [V]. | **Sí** a efectos del DOJ; en CCPA el enmascarado reversible **no** es «deidentified» salvo cumplir las tres condiciones **[NV]**. |

### 2.3 Lectura para el producto

1. **Para Elea (que guarda la clave) el dato enmascarado sigue siendo personal** en todas las leyes revisadas. La base legal y el
   mecanismo de transferencia siguen siendo necesarios [conclusión mía, sustentada en los textos de §2.2; **[NV]** como opinión
   legal].
2. **Para el proveedor receptor la cuestión es distinta y está abierta**: si no puede reidentificar con medios razonables, hay
   un argumento de que él recibe datos no personales (criterio relativo, cercano al de la UE y reflejado en el «meios técnicos
   razoáveis» del art. 5 III/12 LGPD y el «medios… razonablemente» de Chile y Perú). Pero (a) el enmascarado cubre solo lo
   detectado, (b) el contexto puede reidentificar, (c) la Res. 19/2024 pide base y mecanismo siempre que *el exportador* transfiera
   datos personales, y el exportador es Elea. **No conviene apoyar el cumplimiento en ese argumento**; es un atenuante, no una
   exención. Validar con abogado por país **[NV]**.
3. **El enmascarado sí ayuda a**: minimización («mínimo necessário», Anexo I art. 9 párr. único), seguridad (Chile art. 14
   quinquies; CE SIC 002/2025 inst. 3.3), reducir el impacto de una brecha o del uso del proveedor para entrenar, y fundar la
   proporcionalidad ante la autoridad. Es la mejor mitigación técnica disponible, no una exención jurídica.
4. **No llamarlo «anonimización» en la documentación ni en la UI.** Tiene consecuencias legales distintas (Chile/Perú: solo
   lo irreversible sale del régimen) y la doc de producto se vende por su honestidad (AGENTS.md, regla de DoD). Texto sugerido:
   «seudonimización reversible de identificadores detectados».

---

## 3. Riesgos específicos de proveedores chinos frente a los alojados en América

### 3.1 API de primera mano de una entidad de la RPC (DeepSeek como caso medido)

| Dimensión | Evidencia |
|---|---|
| **Dónde se almacena** | Política de Privacidad de DeepSeek (última actualización **10-feb-2026**): «we directly collect, process and store your Personal Data in People's Republic of China» [V: https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html]. Controlador: Hangzhou DeepSeek Artificial Intelligence Co., Ltd., domicilio en China [V]. |
| **Retención** | «for as long as necessary to provide our Services and for the other purposes… (such as improving and developing our Services)»; sin plazo fijo [V]. **Sin plazo específico de retención para la API ni opción de retención cero [V ausencia en las tres páginas leídas]**. |
| **Uso para entrenamiento** | La política lista «to train and improve our technology, such as our machine learning models»; los Términos de Uso (27-mar-2026) §4.3 permiten usar *Inputs/Outputs* «to a minimal extent» con de-identificación, con opt-out «Improve the model for everyone» que es un control de la app de consumo [V: https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html]. **Si el payload de la API se usa para entrenar es ambiguo** (los Términos de la Plataforma Abierta del 22/29-abr-2026 remiten a la política de privacidad y ponen en el desarrollador la carga del consentimiento, §3.3, §4.1, §5.5) [V]; tratarlo como riesgo, no como garantía (interpretación mía). |
| **Acceso estatal** | Ley de Inteligencia Nacional (versión 2018) art. 7: «All organizations and citizens shall support, assist, and cooperate with national intelligence efforts»; art. 14: las instituciones de inteligencia pueden requerir «support, assistance, and cooperation» [V en traducción no oficial: https://www.chinalawtranslate.com/en/national-intelligence-law-of-the-p-r-c-2017/ — el texto oficial npc.gov.cn no se pudo abrir]. Ley de Seguridad de Datos art. 35: los órganos de seguridad pública/estatal pueden recabar datos y «relevant organizations and individuals shall cooperate» [V traducción]. Medidas Provisionales de IA Generativa (CAC, 2023) art. 14: los proveedores deben conservar registros y reportar a las autoridades competentes ante uso ilegal [V el texto chino en cac.gov.cn]. La política de DeepSeek también permite compartir con «law enforcement agencies, public authorities» [V]. |
| **Aplicabilidad de la PIPL a no residentes** | PIPL art. 3: se aplica al tratamiento de información de personas naturales **dentro del territorio** de la RPC [V el texto chino de npc.gov.cn]. Un prompt de un brasileño almacenado en servidores chinos queda bajo la PIPL, **sin que ello ofrezca derechos exigibles al titular extranjero**; el regulador de Berlín lo dice: no hay «durchsetzbare Rechte und wirksame Rechtsbehelfe» [V: https://www.datenschutz-berlin.de/pressemitteilung/berliner-datenschutzbeauftragte-meldet-ki-app-deepseek-in-deutschland-bei-apple-und-google-als-rechtswidrigen-inhalt/]. Qué dice la doctrina sobre extraterritorialidad: **[NV]**. |
| **Ley aplicable y fuero** | Términos de Uso §10.1: derecho de la RPC; foro: tribunal de Hangzhou [V]. Incompatible con las cláusulas-padrão brasileñas (cl. 24.1: derecho y tribunales de Brasil) [V]: **un proveedor así difícilmente pueda firmar el Anexo II sin alterar** (conclusión mía). |
| **Datos sensibles** | La política dice que los servicios «are not designed or intended to process sensitive Personal Data» [V] — choca con el uso corporativo. |
| **Precedentes regulatorios** | Garante (Italia), 30-ene-2025: limitación urgente por almacenamiento en la RPC y violaciones de transparencia/seguridad [V: https://www.garanteprivacy.it/home/docweb/-/docweb-display/docweb/10098477]; autoridad de Berlín: notificación a Apple/Google bajo el DSA, 27-jun-2025, por transferencia sin garantías del art. 46 RGPD [V]. Corea (PIPC), Irlanda, Bélgica, Francia: **[NV]**. **Ninguna autoridad de América mencionada en este spike (ANPD, SIC, AAIP, URCDP, Chile, México, Perú) emitió acción contra DeepSeek que yo haya encontrado** [NV: búsqueda negativa limitada]. |

### 3.2 Riesgos propios del *modelo* (valen aun con los pesos alojados fuera de la RPC)

- NIST CAISI (30-sep-2025): los agentes con el modelo más seguro de DeepSeek (R1-0528) siguieron instrucciones maliciosas en promedio **12 veces más** que los modelos de frontera de EE. UU.; cumplieron el 94% de pedidos abiertamente maliciosos con un *jailbreak* común; repitieron **4 veces más** narrativas del PCCh inexactas [V: https://www.nist.gov/news-events/news/2025/09/caisi-evaluation-deepseek-ai-models-finds-shortcomings-and-risks]. **Método**: CAISI descargó los pesos de Hugging Face y los corrió en servidores propios, sin consultar la API de DeepSeek ni de terceros → los hallazgos son del *modelo*, no de la API [V]. Evaluaciones posteriores: Kimi K2 Thinking (12-dic-2025: muy censurado en chino, poco en inglés/español/árabe) [V]; DeepSeek V4 Pro (1-may-2026) [V el título; sin hallazgos nuevos de seguridad en lo que leí].
- Investigaciones de terceros sobre código inseguro condicionado a temas sensibles (CrowdStrike, nov-2025): **[NV]**, solo vistas en resúmenes.
- Riesgo de continuidad: una nota (Reuters, 7-jul-2026) sobre posibles límites de Beijing al acceso exterior a modelos chinos: **[NV]**.

### 3.3 Modelos chinos de pesos abiertos alojados por un proveedor en América

| Alojador | Qué verifiqué |
|---|---|
| AWS Bedrock | Los *Model Deployment Accounts* los opera AWS; «Model providers don't have any access to those accounts… or to customer prompts and completions» [V: https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html]. |
| Fireworks | «does not log or store prompt or generation data for any open models, without explicit user opt-in» [V: https://docs.fireworks.ai/guides/security_compliance/data_handling]. |
| Groq | «By default, Groq does not retain customer data for inference requests»; lo retenido (batch, ajuste fino) queda en GCP de EE. UU. [V: https://console.groq.com/docs/your-data]. |
| OpenRouter | `data_collection: "deny"` («use only providers which do not collect user data»), `zdr: true` («only be routed to endpoints that have a Zero Data Retention policy»), `only`/`ignore`/`allow_fallbacks`; la etiqueta de política es «best knowledge», no fuente definitiva; **ZDR no cubre *plugins* ni herramientas** como búsqueda web [V: https://openrouter.ai/docs/guides/routing/provider-selection, https://openrouter.ai/docs/guides/features/zdr, https://openrouter.ai/docs/guides/privacy/logging]. Soporta enrutado en región UE/EE. UU. solo en planes Business/Enterprise [V]. |
| Azure / Together / Nvidia | Azure: la página que abrí cubre solo «Models sold by Azure» y no aclara si los modelos de terceros entran → **[NV]**; Together y Nvidia: **[NV]**. |

**Qué pasa si el modelo chino está alojado por un proveedor en EE. UU.** (síntesis, parte interpretación **[NV]**):

1. **Flujo de datos**: va al alojador (EE. UU.), bajo sus términos, y no al desarrollador. Para las leyes de América el destino jurídico es **EE. UU.** (no China): rige lo de §1 para EE. UU. (adecuado en CO; DPF en UY; cláusulas/Anexo II en AR/BR/CL; etc.).
2. **FR-028**: la «jurisdicción de inferencia» sería EE. UU.; la «entidad responsable» también. La categoría «procesado en región, entidad de otra jurisdicción» (`spec.md:576-579`) **no** aplica salvo que el alojador sea de la RPC o la propiedad sea ≥50% de la RPC (p. ej. regiones de una nube china en EE. UU. o América: son *covered persons* para el DOJ, §202.211) — **el catálogo debe registrar la entidad, no solo el país de la región**.
3. **Riesgos que persisten**: los del modelo (§3.2); licencias de los pesos (**[NV]**, no leí las de los seis proveedores); y que **OpenRouter pueda enrutar al *endpoint* de primera mano de DeepSeek** si no se excluye (`ignore`/`only`): FR-032 (`spec.md:607-608`) ya exige cero retención y lista de proveedores del administrador.
4. **DOJ**: un modelo de pesos abiertos alojado por una empresa de EE. UU., sin acceso de un *covered person*, no parece una *covered data transaction* (§202.210); la FAQ 77 dice que la nube no es una exención por sí misma, así que depende del acceso del desarrollador chino **[NV]**.

### 3.4 Referencia: proveedores de EE. UU. con API empresarial (términos por defecto)

- OpenAI: «data sent to the OpenAI API is not used to train or improve OpenAI models (unless you explicitly opt in)»; logs de abuso hasta 30 días; ZDR sujeto a aprobación [V: https://platform.openai.com/docs/guides/your-data, sin fecha].
- Anthropic: borrado de *inputs/outputs* a los 30 días (salvo ZDR); contenido marcado por la política de uso, hasta 2 años; por defecto no se entrena con productos comerciales [V: https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data (1-jul-2026), https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training (18-ago-2026)].
- Google (Gemini API de pago): no usa prompts/respuestas para mejorar productos; logs limitados por abuso, «may be stored transiently or cached in any country in which Google or its agents maintain facilities» [V: https://ai.google.dev/gemini-api/terms (28-abr-2026)]. Vertex AI: logging por defecto con excepción solicitable [V].

### 3.5 Comparación resumida

| | API de primera mano (RPC) | Mismo modelo alojado en EE. UU./América | API de un laboratorio de EE. UU. |
|---|---|---|---|
| Destino jurídico del dato | RPC (sin adecuación en ningún país revisado) | EE. UU. (o el país del alojador) | EE. UU. |
| Retención/entrenamiento | Sin plazo, uso para mejorar; control de opt-out de la app de consumo [V] | Del alojador (varios ZDR o sin retención [V]) | 30 días por defecto, sin entrenamiento por defecto [V] |
| Acceso estatal | Ley de Inteligencia, Seguridad de Datos, art. 14 Medidas de IA [V traducción/texto] | Ley de EE. UU. (FISA, etc.: **[NV]** no investigado) | Ley de EE. UU. (**[NV]** no investigado) |
| Recurso del titular | Sin derechos exigibles (Berlín) [V] | Contractual + ley local | Contractual + ley local |
| Riesgo del modelo (censura, jailbreak) | Sí [V CAISI] | **Sí**, igual [V CAISI método] | Menor en las pruebas de CAISI (comparación) [V] |
| Firmable bajo cláusulas AR/BR | Difícil (derecho y fuero de la RPC) [interpretación] | Sí, depende del alojador | Sí, depende del proveedor |

---

## 4. Recomendación de default para Eleia (laboratorio de toda América)

> Recomendaciones de producto basadas en lo anterior; no son asesoramiento legal ni cumplimiento certificado. Cada punto de
> §1 marcado [NV] queda condicionado a revisión de un abogado.

### 4.1 Bloqueo de APIs chinas por defecto: **SÍ** (mantener FR-029 y afinar el criterio)

- Mantener el bloqueo por defecto de los destinos de primera mano de entidades de la RPC (FR-029, `spec.md:580-584`),
  con habilitación explícita, registrada y con motivo.
- **Razones** ([V] salvo nota): ninguna jurisdicción revisada tiene a China como adecuada; en Colombia las cláusulas modelo no
  levantan la prohibición del art. 26 (CE 003/2025); las cláusulas-padrão de Brasil exigen derecho y tribunales brasileños (cl. 24.1)
  y la política de DeepSeek se rige por el derecho de la RPC; sin retención cero ni plazo; canal legal de acceso estatal; el titular
  no tiene derechos exigibles.
- **Criterio**: bloquear por **entidad responsable y jurisdicción de inferencia** (FR-028), no por dominio ni por familia de modelo.
  Así los pesos chinos alojados por un tercero de América quedan admisibles (§4.2) y las regiones de una nube china también quedan
  bloqueadas.
- **Si se habilita** (decisión del cumplimiento del cliente, FR-029): forzar enmascarado y fail-closed (por FR-031 la RPC está fuera
  de `AMERICAS`), exigir motivo escrito, y que el cliente (no Elea) asuma la base legal. Para Colombia, Perú, Chile, Uruguay y
  Argentina recordar que habrá que sustentar excepción/consentimiento o autorización, y que el consentimiento de un empleado en
  relación de dependencia es frágil (**[NV]**).

### 4.2 Postura fuera de región: **enmascarado forzado con analizador fail-closed**; «rechazar» solo para jurisdicciones de preocupación

| Opción | Evaluación |
|---|---|
| **Permitido** (sin enmascarar) | **No como default.** Contradice la minimización y, para EE. UU., Argentina/Brasil/Chile/Uruguay-sin-DPF no tienen adecuación. |
| **Enmascarado forzado** (FR-031 actual) | **Sí como default para destinos fuera de `AMERICAS`** (UE y resto): la UE es adecuada para AR, BR, CO y UY [V], y el enmascarado es una salvaguarda adicional que reduce el riesgo, sin pretender ser anonimización (§2). |
| **Rechazar** | Reservar para destinos cuya jurisdicción de inferencia o entidad responsable sea de un país de preocupación (RPC y similares) o sin jurisdicción registrada (FR-028: «sin jurisdicción de inferencia, no satisface ninguna lista»). |

- **Observación importante sobre `AMERICAS`** (FR-030, `spec.md:585-594`): la lista «sin enmascarado forzado» incluye EE. UU., que **no es
  adecuado** para Argentina ni Brasil [V] y requiere cláusulas/consentimiento allí; y deja *fuera de región* a la UE, que **sí es
  adecuada** en AR/BR/CO/UY [V]. Es decir, `AMERICAS` es una decisión de **riesgo/negocio** del owner (ya tomada, `spec.md:132-143`), no
  un reflejo del estado jurídico. Mantenerla, pero **no presentarla al cliente como cobertura legal** y no dejar que
  «dentro de la región» se lea como «transferencia lícita».
- El panel/doc debería dejar claro que «mi región» ≠ «base legal resuelta» y que la base la cubre el cliente por fuera del sistema (ya
  dicho en `spec.md:795-797`).

### 4.3 Qué tiene que firmar o registrar Elea por fuera del sistema

(Elea o el cliente, según el rol; ver D4.) Lista de trabajo, por prioridad:

1. **Contrato de encargo/DPA con cada proveedor de modelos** (OpenAI, Anthropic, Google, Azure, OpenRouter y sus alojadores): propósito limitado,
   instrucciones del responsable, **no entrenamiento**, retención acotada o cero (ZDR), subencargados autorizados, borrado al fin, notificación
   de incidentes (BR 3 días hábiles; UY 72 h), derecho de auditoría, legislación y fuero aplicables.
2. **Instrumento de transferencia por país de los datos**: AR — cláusulas Disp. 60/2016 (Anexo II, prestación de servicios) o Res. 198/2023, o
   consentimiento expreso; BR — Anexo II de la Res. 19/2024 **sin alterar** + base art. 7/11 (para la UE basta adecuación + base); CO — contrato
   de transmisión (Dto. 1377 art. 25) y, si el destino no es adecuado, excepción/declaración de conformidad; MX — contrato con el encargado y
   aviso de privacidad con cláusula de transferencias si el proveedor es tercero; CL (desde 1-dic-2026, sujeto al Boletín 18.623-07) — cláusulas con
   garantías adecuadas (art. 27 b); PE — garantías (art. 18.2) y **comunicación a la DGTAIPD** (art. 21); UY — inscripción previa + DPF con declaración,
   o cláusulas autorizadas (Res. 41/021, 8/026), y EIPD previa si el destino no es adecuado.
3. **Registros**: RNBD (Argentina), RNBD (Colombia), Registro URCDP (Uruguay, previo a operar), RNPDP (Perú, comunicación del flujo), ROPA
   (Brasil art. 37).
4. **Evaluación de impacto**: RIPD (BR), EIPD (CL art. 15 ter, UY Dto. 64/020 art. 6 f), estudio de impacto de privacidad (CO CE 002/2024),
   recomendada por la AAIP.
5. **Aviso al titular** (empleados): que existe tratamiento con IA, quién es el encargado, que hay transferencia internacional y a qué país
   (AR, BR, UY Res. 70/023, MX).
6. **DPO/Encarregado/DPD** donde corresponda (BR art. 41; UY >35.000 personas; recomendado en AR).
7. **Registro interno de habilitaciones** de destinos bloqueados por defecto (motivo, quién, cuándo): el sistema lo audita (metadata-only);
   Elea guarda la justificación jurídica.
8. **Si hay datos de personas de EE. UU.** (empleados en EE. UU., ciudadanos de EE. UU.): programa de cumplimiento del DOJ (§202.1001) y no
   enviar datos masivos a *covered persons*.
9. **Revisión por abogado** de cada jurisdicción donde se venda (§1.9).

### 4.4 Defaults concretos (resumen)

| Eje | Default recomendado |
|---|---|
| APIs de primera mano de entidades de la RPC | **Bloqueadas** (FR-029); habilitación explícita, registrada y con motivo |
| Pesos chinos alojados por terceros de América | Permitidos solo en alojadores nombrados (lista del administrador), con ZDR, `data_collection: deny`, `only/ignore`; **sin comodín de OpenRouter** |
| Destinos en `AMERICAS` | Sin enmascarado forzado (decisión del owner) pero con advertencia: no es base legal |
| Destinos fuera de `AMERICAS` (UE y resto) | **Enmascarado forzado, analizador fail-closed** (FR-027/031) |
| Destino sin jurisdicción registrada o de país de preocupación | **Rechazar** |
| Sin postura explícita | Tráfico no redirigido *apagado*, redirigido en «solo región de la empresa» (FR-031) |
| Documentación de producto | «Seudonimización reversible», no «anonimización»; leyenda 🟡 hasta que un abogado confirme |

---

## 5. Decisiones para el owner (cada una con recomendación)

| # | Decisión | Recomendación |
|---|---|---|
| **D1** | ¿Bloquear por defecto las APIs chinas de primera mano? | **Sí**; mantener FR-029; criterio por *entidad responsable + jurisdicción de inferencia*. |
| **D2** | Postura por defecto fuera de región: rechazar, enmascarado forzado o permitido. | **Enmascarado forzado + fail-closed** (FR-031 tal cual); rechazar solo país de preocupación / sin jurisdicción. |
| **D3** | ¿Se mantiene `AMERICAS` como «mi región»? | **Mantener** (decisión ya tomada), pero presentarlo como **criterio de riesgo, no de legalidad**; agregar nota en panel/doc; no prometer cobertura legal. Alternativa más conservadora: sembrar por defecto «país de la instalación + países adecuados del perfil» y que `AMERICAS` sea opt-in; **no recomendado** porque contradice la decisión del owner (`spec.md:136-143`), pero es la lectura más fiel al derecho. |
| **D4** | ¿Elea es *responsable* o *encargado*? | **Definir por instalación y escribirlo en el contrato**: en la instalación de Elea misma, Elea es responsable de los datos de sus empleados; en una instalación de cliente, el cliente suele ser responsable y Elea su encargado/proveedor, y la base legal de las transferencias es del cliente. Este análisis siguió el encargo (obligaciones «del responsable (Elea)»), pero **un abogado debe confirmar el rol** porque cambia quién firma y quién registra. |
| **D5** | Modelos chinos alojados en América. | **Permitir solo en alojadores nombrados y con ZDR**; tratar los pesos como no confiables (guardarraíles, evaluación). No usar comodines de enrutado. |
| **D6** | Qué instrumento de transferencia por país (cláusulas vs. consentimiento). | **Cláusulas oficiales sin alterar (AR Disp. 60/Res. 198; BR Anexo II)**; **no apoyarse en consentimiento** de empleados como base principal (frágil, revocable, «específico y destacado» en Brasil). |
| **D7** | Calendario Chile (1-dic-2026). | **Planificar como si entrara en vigor** y seguir el Boletín 18.623-07; sin cláusulas modelo de la Agencia, usar cláusulas propias con garantías exigibles y documentar. |
| **D8** | Argentina–EE. UU. (ARTI). | **Tratar EE. UU. como no adecuado** hasta que haya acto de la AAIP; usar cláusulas; revisar el Boletín Oficial al decidir. |
| **D9** | Cumplimiento del Anexo II brasileño con proveedores de IA. | **Exigirlo en la selección de proveedores** para clientes con datos de residentes en Brasil; un proveedor que no pueda firmar sin alterar queda fuera para esos datos. |
| **D10** | Texto de producto sobre enmascarado. | **«Seudonimización reversible»**; nada de «anonimización» ni «cumple con X»; leyenda 🟡 en `docs/docs/**` hasta confirmación legal (regla de DoD, AGENTS.md). |
| **D11** | Presupuesto de revisión legal. | **Sí**: una revisión por jurisdicción de venta antes de comercializar «transferencias internacionales» como capacidad; empezar por AR, BR, CL, CO (vigencias más móviles). |
| **D12** | Registro de entidad responsable en el catálogo (FR-028). | **Sí**: capturar entidad responsable y propiedad (≥50% RPC) además del país de la región; impide que una nube china en América pase como «en región». *Es un cambio a la spec 057/069 a evaluar por el owner, no se hace desde este spike.* |

---

## 6. No verificado

Lo que sigue **no** está confirmado contra una fuente oficial abierta en esta sesión; cada punto se puede cerrar con la
acción indicada.

**Normativa por país**
1. **AR**: entrada en vigor del ARTI y existencia de acto de la AAIP que reconozca a EE. UU. (verificar Boletín Oficial); texto del Anexo de la Res. 198/2023; Res. AAIP 34/2019, 159/2018 y 161/2023 (no abiertas); si toda base privada con tratamiento comercial debe inscribirse en el RNBD; estado de los proyectos de reforma (3397-D-2026, 1751-D-2026); Res. 179/2025.
2. **BR**: cambios por Lei 15.352/2026 y 15.452/2026; contenido de la retificação de 18-ago-2025 de la Res. 19/2024; montos mínimos del Apéndice II de la Res. 4/2023; NT 27/2024 y NT 39/2024 (ilegibles/no abiertas); afirmaciones secundarias sobre guías de IA 2026 e «intensificación» de fiscalización; calendario del PL 2338/2023 en la Cámara.
3. **CO**: vigencia de Dto. 1377 art. 24 num. 2 y art. 25 tras el Dto. 1074/2015; si el Título V de la Circular Única se modificó después de jun-2026; número de Diario Oficial de la CE 003/2025; pronunciamiento de la SIC sobre transmisión a encargado en país no adecuado; concepto SIC 25-632634 (el PDF adjunto era de otro asunto); cifras del proyecto de reforma; umbrales del RNBD (Dto. 090/2018).
4. **MX**: vigencia del Reglamento de 2011 bajo la ley nueva; lineamientos o reglamento nuevos 2026; valor de la UMA 2026; la nota original del DOF del 20-mar-2025 (la ley se leyó en el texto consolidado de Diputados).
5. **CL**: resultado del Boletín 18.623-07 después del 22-sep-2026; si hay nuevo Consejo de la Agencia; cómputo de «1-dic-2026» (el texto dice «primer día del mes 24º», el resultado lo deduje); declaraciones oficiales de IA.
6. **PE**: lista de países adecuados (art. 19 del Reglamento); texto de la RD 074-2022-JUS/DGTAIPD; fecha exacta de publicación y vigencia del DS 016-2024-JUS; reformas posteriores de la Ley 29733; valor de la UIT 2026.
7. **UY**: actualizaciones posteriores a la Res. 63/023; texto completo de la Res. 8/026; fecha de depósito y vigencia del Protocolo 108+; Res. 50/022; pronunciamientos de la URCDP/AGESIC sobre IA generativa.
8. **EE. UU.**: aplicabilidad de 28 CFR 202 a APIs de IA y a modelos chinos alojados por terceros (interpretación mía); listado oficial de leyes estatales en vigor y sus reguladores (solo secundarias); ausencia de restricciones estatales/federales a exportar datos de no residentes (negativo no exhaustivo); `justice.gov/nsd/data-security-program` (404 al intentar, así que no descarto cambios posteriores a las FAQ de sept-2025); acciones de *enforcement* del DOJ; apelación C-703/25 P; caso FTC/Match-OkCupid; prohibiciones estatales de apps chinas en dispositivos de gobierno.

**Proveedores chinos y alojadores**
9. Texto oficial (npc.gov.cn) de la Ley de Inteligencia Nacional y de la Ley de Seguridad de Datos (se leyeron traducciones no oficiales); texto de la enmienda a la Ley de Ciberseguridad vigente desde 1-ene-2026; comentario autorizado sobre aplicación extraterritorial de la PIPL a no residentes.
10. Acciones de Corea (PIPC), Irlanda, Bélgica y Francia contra DeepSeek; acciones de autoridades de América (resultado negativo limitado); hallazgos de CrowdStrike/Booz Allen; la noticia de Reuters del 7-jul-2026.
11. Políticas de privacidad de Alibaba/Qwen, Moonshot/Kimi, Zhipu/GLM, MiniMax y ByteDance/Doubao (no abiertas; se presume exposición legal equivalente, interpretación mía); licencias de los pesos abiertos; políticas de Together AI y Nvidia; si Azure trata los modelos de terceros como «sold by Azure»; régimen de acceso estatal de EE. UU. (FISA, CLOUD Act) sobre los alojadores y laboratorios estadounidenses.
12. Comportamiento del enrutado de OpenRouter más allá de lo documentado (las etiquetas de política son «best knowledge» según su propia doc).

**Interpretaciones propias (no son texto de norma)**
13. Que el dato enmascarado reversible siga siendo personal para Elea en cada país (§2.2, derivado de las definiciones); el argumento relativo para el receptor (§2.3); que la API de modelo encaje en el régimen de «tercerización» peruano; que la ubicación del modelo en un alojador estadounidense cambie el destino jurídico a EE. UU.; que un proveedor de la RPC no pueda firmar el Anexo II brasileño; que el consentimiento de empleados sea frágil.
14. El cómputo del **1-dic-2026** para Chile, la fecha de vigencia del DS 016-2024-JUS en Perú, y la acumulación «hasta $50.000.000» en Argentina (×500, aritmética del agente).

**Del producto (spec 057)**
15. Este spike leyó `spec.md` de la rama `origin/057-porte-sentinel-068-redireccion-modelos` @ `29311ef`; no leyó `plan.md`, el catálogo real de destinos ni el código de la extensión que se va a portar, por lo que **cómo clasificará FR-028 a un modelo chino alojado por un tercero** debe verificarse al implementar (D12).

---

## Anexo — Fuentes de conjunto

Argentina: infoleg (Ley 25.326, Dto. 1558/2001, Disp. 60-E/2016, Res. 198/2023), argentina.gob.ar (AAIP, Res. 126/2024, Guía de IA), USTR (ARTI).
Brasil: planalto.gov.br (LGPD), in.gov.br (Res. CD/ANPD 19/2024 y 32/2026), gov.br/anpd, dspace.mj.gov.br (Res. 4/2023).
Colombia: secretariasenado.gov.co (Ley 1581), normograma MinTIC y Cancillería (Dto. 1377, CE 005/2017, 002/2024, 002/2025), sedeelectronica.sic.gov.co (CE 003/2025, proyecto Título V).
México: diputados.gob.mx (ley nueva), dof.gob.mx (Reglamento 2011).
Chile: leychile.cl (Leyes 21.719 y 19.628), senado.cl, economia.gob.cl.
Perú: leyes.congreso.gob.pe (Ley 29733), smv.gob.pe (DS 016-2024-JUS).
Uruguay: impo.com.uy (Leyes 18.331, 19.670, 20.212; Dtos. 414/009 y 64/020), gub.uy/URCDP (resoluciones 23/021, 41/021, 63/023, 70/023, 8/026).
EE. UU.: ecfr.gov (28 CFR 202), federalregister.gov, justice.gov (FAQ), ftc.gov, cppa.ca.gov.
China y proveedores: cdn.deepseek.com, cac.gov.cn, npc.gov.cn, chinalawtranslate.com (traducciones no oficiales), nist.gov, garanteprivacy.it, datenschutz-berlin.de, docs.aws.amazon.com, docs.fireworks.ai, console.groq.com, openrouter.ai, platform.openai.com, privacy.claude.com, ai.google.dev.
