"""Datos compartidos de los tests de residencia de la 057 T-E (T052–T057, T094, T098).

Genérico: la región de prueba se llama `AMERICAS` solo porque es el dato que siembra Eleia; ningún código de
`sentinel/redirect` nombra una región (Principio IV)."""
from sentinel.redirect.residency import effective_posture, evaluate
from sentinel.redirect.scopes import RequestScope

T1, T2 = "t1", "t2"
SCOPE = RequestScope(tenant_id=T1, connection_id="k1", user_id="u1", group_ids=("g1",))

AMERICAS_JURISDICTIONS = (
    "US", "CA", "MX", "BZ", "CR", "SV", "GT", "HN", "NI", "PA",
    "AG", "BS", "BB", "CU", "DM", "DO", "GD", "HT", "JM", "KN", "LC", "VC", "TT", "PR",
    "AR", "BO", "BR", "CL", "CO", "EC", "GY", "PY", "PE", "SR", "UY", "VE", "LATAM")


def region_row(default_posture="masked_all", *, name="AMERICAS", level="installation", tenant_id=None,
               profiles=("latam_ar", "latam", "us"), jurisdictions=AMERICAS_JURISDICTIONS, is_zone=True):
    return {"id": f"r-{name}-{level}", "level": level, "tenant_id": tenant_id, "name": name,
            "jurisdictions": list(jurisdictions), "region_profiles": list(profiles),
            "default_posture": default_posture, "is_zone": is_zone}


def row(mode, jurisdictions=(), *, role="compliance_officer", scope=("tenant", "*"), accept=False, tenant_id=T1):
    return {"tenant_id": tenant_id, "scope_type": scope[0], "scope_value": scope[1], "mode": mode,
            "jurisdictions": list(jurisdictions), "accept_foreign_entity": accept, "created_by_role": role}


def dest(inf="US", ent="US", ctrl="US", *, id="d1"):
    return {"id": id, "inference_jurisdiction": inf, "entity_jurisdiction": ent, "control_jurisdiction": ctrl}


def posture(rows=(), *, region="latam_ar", regions=(), redirected=True, relaxations=(), scope=SCOPE):
    return effective_posture(list(rows), scope, redirected=redirected, tenant_region=region,
                             regions=list(regions), relaxations=list(relaxations))


def verdict(rows=(), destination=None, **kw):
    return evaluate(posture(rows, **kw), destination or dest())


def relaxation(entry_id="d1", *, tenant_id=None, level="installation"):
    return {"entry_id": entry_id, "level": level, "tenant_id": tenant_id}
