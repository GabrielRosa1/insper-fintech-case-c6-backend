from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, JSON, ARRAY
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class RoleEnum(str, enum.Enum):
    user      = "user"
    assistant = "assistant"


class FeedbackEnum(str, enum.Enum):
    positive = "positive"
    negative = "negative"


class ChatThread(Base):
    """
    Sessão de conversa entre um usuário e o assistente de employer branding.
    Um thread agrupa N mensagens em ordem cronológica e mantém o contexto
    da empresa alvo para personalização do system prompt.
    """
    __tablename__ = "chat_threads"

    id = Column(String(36), primary_key=True)           # UUID v4

    # Contexto
    title           = Column(Text, nullable=True)        # Auto-gerado da 1ª pergunta
    target_company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=True, index=True
    )
    user_identifier = Column(String(255), nullable=True, index=True)  # email, user_id, etc.

    # Metadados extras (filtros ativos, fonte de acesso, etc.)
    metadata_       = Column("metadata", JSONB, nullable=True)

    # Contadores — denormalizados para evitar COUNT(*) em listagens
    message_count   = Column(Integer, default=0, nullable=False)
    last_message_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    company  = relationship("Company")
    messages = relationship(
        "ChatMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self):
        return f"<ChatThread id={self.id} msgs={self.message_count} title='{(self.title or '')[:40]}'>"


class ChatMessage(Base):
    """
    Mensagem individual dentro de um ChatThread.

    Para mensagens do usuário:
        - content = texto da pergunta
        - embedding_query = query usada para o RAG

    Para mensagens do assistente:
        - content = resposta em markdown
        - sources = reviews usadas como evidência (JSONB)
        - review_ids_used = IDs das reviews para rastreabilidade
        - tokens_used / latency_ms = métricas de custo e performance
        - feedback = avaliação do usuário (positive | negative)
    """
    __tablename__ = "chat_messages"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(
        String(36),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Conteúdo
    role    = Column(String(20), nullable=False)   # "user" | "assistant"
    content = Column(Text, nullable=False)

    # RAG — só preenchido em mensagens do assistente
    sources         = Column(JSONB, nullable=True)              # Reviews citadas como evidência
    review_ids_used = Column(ARRAY(Integer), nullable=True)     # IDs das reviews para JOIN
    embedding_query = Column(Text, nullable=True)               # Query enviada ao Voyage

    # Métricas de custo e performance
    tokens_used = Column(Integer, nullable=True)                # Input + output tokens
    model_used  = Column(String(100), nullable=True)            # "claude-haiku-4-5-20251001"
    latency_ms  = Column(Integer, nullable=True)                # Tempo total da resposta

    # Qualidade
    feedback = Column(String(20), nullable=True)                # "positive" | "negative" | null

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    thread = relationship("ChatThread", back_populates="messages")

    def __repr__(self):
        preview = (self.content or "")[:50].replace("\n", " ")
        return f"<ChatMessage id={self.id} role={self.role} '{preview}'>"

    @property
    def is_user(self) -> bool:
        return self.role == "user"

    @property
    def is_assistant(self) -> bool:
        return self.role == "assistant"

    @property
    def has_positive_feedback(self) -> bool:
        return self.feedback == "positive"

    @property
    def cost_usd(self) -> float | None:
        """Estimativa de custo em USD baseada no modelo e tokens."""
        if not self.tokens_used or not self.model_used:
            return None
        # claude-haiku-4-5: input $0.80/MTok, output $4.00/MTok (aprox. 80/20)
        if "haiku" in self.model_used:
            return round(self.tokens_used * 0.000_001 * 1.60, 6)
        # claude-sonnet-4-5: input $3.00/MTok, output $15.00/MTok (aprox. 80/20)
        if "sonnet" in self.model_used:
            return round(self.tokens_used * 0.000_001 * 5.40, 6)
        return None