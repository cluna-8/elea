import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class Group(Base):
    __tablename__ = "groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False, index=True)
    description = Column(String, nullable=True)
    engine_team_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Compliance profile fields (Feature 006)
    default_legal_basis = Column(String, nullable=True)       # e.g. art_9_2_h
    default_risk_level = Column(String, nullable=True)        # e.g. high_risk_annex3
    compliance_project_id = Column(UUID(as_uuid=True), ForeignKey("compliance_projects.id"), nullable=True)

    # Relationships
    users = relationship("User", back_populates="group")
    api_keys = relationship("APIKey", back_populates="group")
    budgets = relationship("Budget", back_populates="group")
    compliance_project = relationship("ComplianceProject", foreign_keys=[compliance_project_id])

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False) # admin, compliance_officer, clinician, developer
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True)
    engine_user_id = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    group = relationship("Group", back_populates="users")
    api_keys = relationship("APIKey", back_populates="user")
    budgets = relationship("Budget", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")
    consent_records = relationship("ConsentRecord", back_populates="user")
