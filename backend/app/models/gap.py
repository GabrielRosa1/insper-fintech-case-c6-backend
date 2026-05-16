from sqlalchemy import (
    Column, Integer, Float, String, Text, DateTime, ForeignKey, JSON, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class GapDirectionEnum(str, enum.Enum):
    promise_better = "promise_better"  # Vagas prometem mais do que reviews confirmam
    reality_better = "reality_better"  # Realidade é melhor que a imagem externa
    aligned = "aligned"                # Discurso e realidade alinhados


class DiscourseRealityGap(Base):
    """
    Cruzamento entre o que as vagas prometem e o que os funcionários vivem.
    É o diferencial estratégico desta solução — identifica onde a empresa
    está se prejudicando na atração de talentos com promessas não cumpridas.

    Exemplos:
    - C6 Bank: vagas 98% presencial × reviews: presencial é maior queixa
      → Gap CRÍTICO: candidatos descartam antes de entrevistar

    - Nubank: vagas mencionam "cultura forte" × reviews pós-RTO: "cultura acabou"
      → Gap: promessa não entregue, candidatos vão se decepcionar ao entrar
    """
    __tablename__ = "discourse_reality_gaps"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    dimension_id = Column(Integer, ForeignKey("dimensions.id"), nullable=False)
    analysis_version = Column(String(20), index=True)

    # O que as vagas prometem
    jobs_signal = Column(Text)              # Descrição do sinal nas vagas
    jobs_pct_mentioning = Column(Float)     # % das vagas que mencionam este tema

    # O que as reviews dizem
    reviews_sentiment_score = Column(Float) # Score de sentimento nas reviews
    reviews_pct_negative = Column(Float)    # % de menções negativas

    # Análise do gap
    gap_direction = Column(Enum(GapDirectionEnum))
    gap_severity = Column(Integer)          # 1-5 (5 = crítico)
    gap_description = Column(Text)          # Descrição humana do gap

    # Evidências
    supporting_job_examples = Column(JSON)  # [job_id, ...] exemplos de vagas
    supporting_review_ids = Column(JSON)    # [review_id, ...] reviews que evidenciam

    # Recomendação estratégica
    recommendation = Column(Text)

    calculated_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company")
    dimension = relationship("Dimension")

    def __repr__(self):
        return f"<Gap company={self.company_id} dim={self.dimension_id} severity={self.gap_severity}>"