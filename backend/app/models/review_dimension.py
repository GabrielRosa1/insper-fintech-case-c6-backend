from sqlalchemy import (
    Column, Integer, Float, Text, Boolean,
    DateTime, ForeignKey, Enum, String
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class DimensionSentimentEnum(str, enum.Enum):
    positivo = "positivo"
    negativo = "negativo"
    misto = "misto"
    neutro = "neutro"


class ReviewDimension(Base):
    """
    Relação N:N entre Review e Dimension.
    Uma review pode tocar em 7 dimensões, cada uma com sentimento próprio.

    Exemplo:
    - Review 42, liderança → negativo, intensidade 8
      evidence_quote: "gestão completamente despreparada, top-down atrás de top-down"
    - Review 42, salario_beneficios → positivo, intensidade 6
      evidence_quote: "salário acima do mercado, RSUs muito boas"
    """
    __tablename__ = "review_dimensions"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False, index=True)
    dimension_id = Column(Integer, ForeignKey("dimensions.id"), nullable=False, index=True)
    analysis_version = Column(String(20), index=True)

    # Sentimento específico desta dimensão nesta review
    sentiment = Column(Enum(DimensionSentimentEnum), nullable=False)

    # Intensidade (1-10) do sentimento para esta dimensão
    intensity = Column(Integer)

    # Trecho exato da review que justifica a classificação (para RAG e evidências)
    evidence_quote = Column(Text)

    # Confiança da IA na classificação (0-1)
    confidence = Column(Float)

    # Se esta dimensão é o tema principal da review
    is_primary = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    review = relationship("Review", back_populates="dimensions")
    dimension = relationship("Dimension", back_populates="review_dimensions")

    def __repr__(self):
        return f"<ReviewDimension review={self.review_id} dim={self.dimension_id} sent={self.sentiment}>"