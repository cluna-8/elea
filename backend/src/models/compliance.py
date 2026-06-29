import uuid
from datetime import date, datetime
from sqlalchemy import Column, String, Boolean, Integer, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from ..database import Base


class ComplianceProject(Base):
    __tablename__ = "compliance_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    legal_basis = Column(String, nullable=False)
    legal_basis_notes = Column(Text, nullable=True)
    data_category = Column(String, default="standard")
    ai_act_risk_level = Column(String, default="limited")
    is_active = Column(Boolean, default=False)
    eu_region_required = Column(Boolean, default=False)
    human_review_required = Column(Boolean, default=False)
    ai_disclosure_enabled = Column(Boolean, default=True)
    ai_disclosure_message = Column(Text, nullable=True)
    dpia_reference = Column(String, nullable=True)
    dpia_version = Column(String, nullable=True)
    dpia_last_reviewed = Column(Date, nullable=True)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(String, default=lambda: datetime.utcnow().isoformat())


class DPARegistry(Base):
    __tablename__ = "dpa_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_name = Column(String, nullable=False)
    dpa_type = Column(String, default="standard")
    signed_date = Column(Date, nullable=True)
    expiration_date = Column(Date, nullable=True)
    covers_special_categories = Column(Boolean, default=False)
    processing_region = Column(String, default="global")
    document_reference = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())


class DataSubjectRequest(Base):
    __tablename__ = "data_subject_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_type = Column(String, nullable=False)
    subject_identifier = Column(String, nullable=False)
    date_received = Column(Date, nullable=False)
    date_completed = Column(Date, nullable=True)
    handled_by = Column(String, nullable=True)
    status = Column(String, default="open")
    outcome_notes = Column(Text, nullable=True)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())


class HumanReview(Base):
    __tablename__ = "human_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_log_id = Column(UUID(as_uuid=True), nullable=True)
    review_token = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    reviewer_id = Column(String, nullable=True)
    action = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    reviewed_at = Column(String, nullable=True)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    log_type = Column(String, unique=True, nullable=False)
    retention_days = Column(Integer, nullable=False)
    justification = Column(Text, nullable=True)
    last_updated = Column(String, default=lambda: datetime.utcnow().isoformat())
    updated_by = Column(String, nullable=True)
    purge_log = Column(JSONB, default=list)
