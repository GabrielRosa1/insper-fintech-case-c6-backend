from sqlalchemy import (
    Column, Integer, Float, String, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class CompanyDimensionStats(Base):
    """
    Agregações pré-calculadas por empresa × dimensão × período.
    Serve como cache para o dashboard — evita recalcular a cada request.
    Regenerado pelo pipeline 04_aggregate.py sempre que nova análise roda.

    period = "all" | "2023" | "2024" | "2025" | "2026" | "last_6m" | "last_12m"
    """
    __tablename__ = "company_dimension_stats"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    dimension_id = Column(Integer, ForeignKey("dimensions.id"), nullable=False, index=True)
    analysis_version = Column(String(20), index=True)
    period = Column(String(20), nullable=False, index=True)  # "all", "2025", "last_6m"

    # Volumes
    total_mentions = Column(Integer, default=0)
    positive_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    mixed_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)

    # Scores (0-10)
    sentiment_score = Column(Float)          # Score geral ponderado
    avg_intensity = Column(Float)            # Intensidade emocional média
    mention_rate = Column(Float)             # % de reviews que mencionam esta dimensão

    # Temas mais frequentes nesta dimensão
    top_themes = Column(JSON)                # [{"tema": "burnout", "count": 45}, ...]

    # Quotes de evidência (3 melhores por sentimento)
    top_positive_quotes = Column(JSON)       # [{review_id, quote, intensity}, ...]
    top_negative_quotes = Column(JSON)

    calculated_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="dimension_stats")
    dimension = relationship("Dimension", back_populates="stats")

    def __repr__(self):
        return f"<Stats company={self.company_id} dim={self.dimension_id} period={self.period}>"