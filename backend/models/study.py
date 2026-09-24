"""Learning data is independent of conversational memories."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from models.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class StudyDeck(Base):
    __tablename__ = "study_decks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(120), nullable=False)
    archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class StudyItem(Base):
    __tablename__ = "study_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deck_id = Column(UUID(as_uuid=True), ForeignKey("study_decks.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    knowledge_point = Column(String(120), nullable=False)
    prompt = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    explanation = Column(Text, nullable=False)
    options = Column(JSON, nullable=False, default=list)
    source = Column(JSON, nullable=False)
    archived = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)
    fsrs_card = Column(JSON, nullable=False)
    due = Column(DateTime(timezone=True), nullable=False, index=True)
    review_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class StudySession(Base):
    __tablename__ = "study_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode = Column(String(20), nullable=False)
    filters = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    recap = Column(Text)


class StudyAttempt(Base):
    __tablename__ = "study_attempts"
    __table_args__ = (UniqueConstraint("session_id", "item_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("study_sessions.id"), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey("study_items.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    item_version = Column(Integer, nullable=False)
    answer = Column(Text)
    feedback = Column(JSON)
    objective_correct = Column(Boolean)
    rating = Column(Integer)
    submitted_at = Column(DateTime(timezone=True))
    reviewed_at = Column(DateTime(timezone=True), index=True)
    fsrs_log = Column(JSON)
    next_due = Column(DateTime(timezone=True))
    confirmation_id = Column(UUID(as_uuid=True), unique=True)
