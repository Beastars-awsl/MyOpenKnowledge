from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["flashcard", "choice", "short_answer"]


class StudyModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", from_attributes=True)


class ModelSettings(StudyModel):
    model: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=40)
    apiKey: str = Field(default="", max_length=4096)
    baseUrl: Optional[str] = Field(default=None, max_length=2048)


class Source(StudyModel):
    mode: Literal["document", "text", "topic"]
    document_id: Optional[UUID] = None
    title: str = Field(default="", max_length=255)
    chunk_index: Optional[int] = Field(default=None, ge=0)
    excerpt: str = Field(default="", max_length=16000)

    @model_validator(mode="after")
    def validate_source(self):
        if self.mode == "document" and (not self.document_id or self.chunk_index is None):
            raise ValueError("文档来源必须包含文档和分块编号")
        if self.mode != "topic" and not self.excerpt:
            raise ValueError("资料出题必须保留原文摘录")
        if self.mode != "document" and self.document_id:
            raise ValueError("非文档来源不能关联文档")
        return self


class ItemContent(StudyModel):
    kind: Kind
    knowledge_point: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(min_length=1, max_length=6000)
    options: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_options(self):
        self.options = [option.strip() for option in self.options]
        if self.kind == "choice":
            if len(self.options) != 4 or len(set(self.options)) != 4 or any(not o or len(o) > 1000 for o in self.options):
                raise ValueError("单选题需要四个不同且非空的选项")
            if self.answer not in self.options:
                raise ValueError("单选题答案必须是一个完整选项")
        elif self.options:
            raise ValueError("此题型不接受选项")
        return self


class ItemDraft(ItemContent):
    source: Source


class GeneratedItem(ItemContent):
    source_index: Optional[int] = Field(default=None, ge=0)
    evidence: str = Field(default="", max_length=16000)


class GeneratedBatch(StudyModel):
    items: list[GeneratedItem] = Field(min_length=1, max_length=20)


class GenerateRequest(ModelSettings):
    mode: Literal["document", "text", "topic"]
    document_id: Optional[UUID] = None
    text: str = Field(default="", max_length=16000)
    focus: str = Field(default="", max_length=1000)
    kinds: list[Kind] = Field(default_factory=lambda: ["flashcard", "choice", "short_answer"], min_length=1, max_length=3)
    count: int = Field(default=10, ge=1, le=20)
    start_chunk: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=8, ge=1, le=12)
    variant_item_id: Optional[UUID] = None


class GenerateResponse(StudyModel):
    items: list[ItemDraft]
    coverage: str


class DeckCreate(StudyModel):
    title: str = Field(min_length=1, max_length=120)


class DeckUpdate(StudyModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    archived: Optional[bool] = None


class DeckResponse(DeckCreate):
    id: UUID
    archived: bool
    created_at: datetime


class SaveItem(ItemDraft):
    id: UUID


class SaveItems(StudyModel):
    # Client-generated IDs make saving the same preview safe to retry.
    items: list[SaveItem] = Field(min_length=1, max_length=20)


class ItemResponse(ItemDraft):
    id: UUID
    deck_id: UUID
    archived: bool
    version: int
    due: datetime
    review_count: int
    source_available: bool


class ItemUpdate(ItemContent):
    version: int = Field(ge=1)


class ArchiveRequest(StudyModel):
    archived: bool
    version: int = Field(ge=1)


class SessionCreate(StudyModel):
    id: UUID
    mode: Literal["daily", "weak", "mistakes"] = "daily"
    deck_id: Optional[UUID] = None
    knowledge_point: str = Field(default="", max_length=120)
    kind: Optional[Kind] = None
    limit: int = Field(default=20, ge=1, le=100)


class AnswerRequest(ModelSettings):
    answer: str = Field(default="", max_length=8000)


class ConfirmRequest(StudyModel):
    confirmation_id: UUID
    version: int = Field(ge=1)
    rating: int = Field(ge=1, le=4)


class Feedback(StudyModel):
    summary: str = Field(min_length=1, max_length=6000)
    omissions: list[str] = Field(default_factory=list, max_length=20)
    misconceptions: list[str] = Field(default_factory=list, max_length=20)
    suggested_rating: int = Field(ge=1, le=4)
    unavailable: bool = False


class QuestionView(StudyModel):
    kind: Kind
    knowledge_point: str
    prompt: str
    options: list[str]
    answer: Optional[str] = None
    explanation: Optional[str] = None
    source: Optional[Source] = None


class AttemptResponse(StudyModel):
    id: UUID
    item_id: UUID
    position: int
    item_version: int
    question: QuestionView
    answer: Optional[str]
    feedback: Optional[Feedback]
    objective_correct: Optional[bool]
    rating: Optional[int]
    reviewed_at: Optional[datetime]
    next_due: Optional[datetime]
    source_available: bool
    unavailable: bool
    intervals: dict[str, datetime]


class SessionResponse(StudyModel):
    id: UUID
    mode: str
    created_at: datetime
    completed_at: Optional[datetime]
    recap: Optional[str]
    attempts: list[AttemptResponse]


class WeakPoint(StudyModel):
    knowledge_point: str
    samples: int
    weak_count: int
    ratio: float


class DailyCount(StudyModel):
    date: str
    reviewed: int
    recalled: int
    choice_count: int
    choice_correct: int
    flashcard_count: int
    flashcard_recalled: int


class SessionSummary(StudyModel):
    id: UUID
    mode: str
    created_at: datetime
    completed_at: Optional[datetime]
    total: int
    confirmed: int


class StatsResponse(StudyModel):
    due: int
    new: int
    reviewed_today: int
    weak_points: list[WeakPoint]
    trend: list[DailyCount]
    upcoming: list[dict]
    sessions: list[SessionSummary]
