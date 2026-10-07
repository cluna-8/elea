"""Modelos de los perfiles de acceso (069 data-model §2; T046; capa 2).

Metadata PROPIA (`AccessBase`), como el catálogo: la base no se entera de estas tablas. El perfil de
una llave NO vive en una columna de `api_keys` (la base no se toca): es una fila de
`ext_access_key_profile`. Las llaves foráneas a `tenants` y la RLS viven en la migración.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Uuid, func)
from sqlalchemy.orm import declarative_base

AccessBase = declarative_base()

KINDS = ("company", "ceiling", "key")
EFFECTS = ("include", "exclude")
# Selectores de regla. «Bloqueados» (entradas `blocked_by_default` sin habilitar) no es un selector:
# el catálogo ya las deja fuera del servicio, así que nunca llegan al resolutor.
SELECTORS = ("semaforo", "jurisdiccion", "proveedor", "capacidad", "entrada")
SUBJECT_TYPES = ("tenant", "group", "user")
RISK_LEVELS = ("minimal", "limited", "high_risk_annex1", "high_risk_annex3")


def UUID(as_uuid=True):  # noqa: N802
    return Uuid(as_uuid=as_uuid)


def _pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _stamps():
    return (Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
            Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
                   nullable=False))


class AccessProfile(AccessBase):
    __tablename__ = "ext_access_profile"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    name = Column(String(128), nullable=False)
    seeded = Column(Boolean, nullable=False, default=False)
    archived_at = Column(DateTime(timezone=True))
    archived_reason = Column(Text)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(UUID(as_uuid=True))
    updated_by = Column(UUID(as_uuid=True))
    created_at, updated_at = _stamps()


class AccessProfileRule(AccessBase):
    __tablename__ = "ext_access_profile_rule"
    id = _pk()
    profile_id = Column(UUID(as_uuid=True), ForeignKey("ext_access_profile.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    effect = Column(String(8), nullable=False)
    selector = Column(String(16), nullable=False)
    value = Column(Text, nullable=False)


class AccessAssignment(AccessBase):
    __tablename__ = "ext_access_assignment"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("ext_access_profile.id"), nullable=False,
                        index=True)
    subject_type = Column(String(8), nullable=False)
    subject_id = Column(UUID(as_uuid=True), nullable=False)


class AiActCeiling(AccessBase):
    __tablename__ = "ext_ai_act_ceiling"
    tenant_id = Column(UUID(as_uuid=True), primary_key=True)
    risk_level = Column(String(24), primary_key=True)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("ext_access_profile.id"), nullable=False)


class AccessKeyProfile(AccessBase):
    __tablename__ = "ext_access_key_profile"
    api_key_id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("ext_access_profile.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
                        nullable=False)


TABLES = tuple(m.__tablename__ for m in (AccessProfile, AccessProfileRule, AccessAssignment,
                                         AiActCeiling, AccessKeyProfile))
