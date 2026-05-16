from sqlalchemy import (
    Column, Integer, String, Text, Date, Boolean,
    DateTime, ForeignKey, Enum, Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class EventTypeEnum(str, enum.Enum):
    layoff = "layoff"
    rto = "rto"                        # Return to office
    ipo = "ipo"
    lideranca = "lideranca"            # Mudança de liderança
    politica = "politica"              # Mudança de política interna
    crescimento = "crescimento"        # Expansão acelerada
    crise = "crise"
    outro = "outro"


class EventSourceEnum(str, enum.Enum):
    auto_detected = "auto_detected"    # Change-point detection
    manual = "manual"                  # Cadastrado manualmente
    ai_identified = "ai_identified"    # Claude identificou nas reviews


class CompanyEvent(Base):
    """
    Eventos que marcam divisores de águas no sentimento.
    Detectados automaticamente por change-point detection ou cadastrados manualmente.

    Exemplos:
    - C6 Bank: layoff fev/2023 → queda brusca no sentimento
    - Nubank: RTO nov/2025 → queda brusca, domina reviews negativas
    - Nubank: IPO dez/2021 → início de mudança cultural
    """
    __tablename__ = "company_events"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Dados do evento
    nome = Column(String(200), nullable=False)
    descricao = Column(Text)
    event_type = Column(Enum(EventTypeEnum))
    data_evento = Column(Date, index=True)
    source = Column(Enum(EventSourceEnum), default=EventSourceEnum.auto_detected)

    # Impacto no sentimento (calculado pelo pipeline)
    sentiment_before = Column(Float)     # Média de sentimento 3 meses antes
    sentiment_after = Column(Float)      # Média de sentimento 3 meses depois
    sentiment_delta = Column(Float)      # after - before (negativo = piorou)
    review_volume_delta = Column(Float)  # % de aumento no volume de reviews

    # Confiança da detecção automática
    confidence = Column(Float)
    is_confirmed = Column(Boolean, default=False)  # Confirmado manualmente

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="events")

    def __repr__(self):
        return f"<CompanyEvent {self.company_id} {self.event_type} {self.data_evento}>"