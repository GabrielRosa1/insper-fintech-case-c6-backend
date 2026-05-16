from sqlalchemy import (
    Column, Integer, Float, String, Text, Boolean,
    DateTime, ForeignKey, JSON, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class InsightTypeEnum(str, enum.Enum):
    oportunidade_captacao = "oportunidade_captacao"     # C6 pode captar talentos do Nubank
    risco_retencao = "risco_retencao"                   # Algo está fazendo gente sair do C6
    gap_discurso_realidade = "gap_discurso_realidade"   # Promessa ≠ Entrega
    vantagem_competitiva = "vantagem_competitiva"       # C6 ganha em algo vs concorrente
    ponto_cego = "ponto_cego"                           # C6 não percebe problema latente
    benchmark_positivo = "benchmark_positivo"           # Algo bom que o concorrente faz
    recomendacao_acao = "recomendacao_acao"             # Ação concreta recomendada
    tendencia_temporal = "tendencia_temporal"           # Padrão que muda ao longo do tempo


class InsightPriorityEnum(str, enum.Enum):
    critica = "critica"     # Atuar imediatamente
    alta = "alta"           # Próximo trimestre
    media = "media"         # Próximo semestre
    baixa = "baixa"         # Backlog


class Insight(Base):
    """
    Insights estratégicos gerados pela IA (camada macro).
    Cada insight tem evidências rastreáveis nas reviews e um plano de ação concreto.

    target_company = empresa que usa a plataforma (C6 Bank)
    compared_company = empresa comparada (Nubank, ou null para insights sem comparação)
    """
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True)
    target_company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    compared_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    analysis_version = Column(String(20), index=True)

    # Classificação
    insight_type = Column(Enum(InsightTypeEnum), nullable=False, index=True)
    priority = Column(Enum(InsightPriorityEnum), nullable=False)

    # Conteúdo
    titulo = Column(String(300), nullable=False)
    descricao = Column(Text, nullable=False)           # Análise completa (2-4 parágrafos)
    headline = Column(String(200))                     # Frase de impacto para C-level

    # Ação recomendada (campo principal solicitado)
    acao_recomendada = Column(Text)                    # O que fazer concretamente
    acao_prazo = Column(String(50))                    # "30 dias", "1 trimestre"
    acao_responsavel = Column(String(100))             # "RH", "Liderança", "C-Level"

    # Estimativa de impacto vs esforço (para priorização)
    impacto_score = Column(Integer)   # 1-5: impacto potencial na captação/retenção
    esforco_score = Column(Integer)   # 1-5: esforço para implementar
    roi_score = Column(Float)         # impacto / esforco (calculado)

    # Evidências rastreáveis
    supporting_review_ids = Column(JSON)    # [42, 137, 289, ...]
    supporting_quotes = Column(JSON)        # [{"review_id": 42, "quote": "...", "empresa": "C6 Bank"}]
    supporting_data = Column(JSON)          # Números e estatísticas que embasam

    # Dimensões relacionadas
    related_dimension_ids = Column(JSON)    # [1, 3, 5]

    # Metadados
    is_verified = Column(Boolean, default=False)  # Revisado por humano
    is_featured = Column(Boolean, default=False)  # Destaque no dashboard
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    target_company = relationship(
        "Company", foreign_keys=[target_company_id], back_populates="insights_as_target"
    )
    compared_company = relationship(
        "Company", foreign_keys=[compared_company_id], back_populates="insights_as_compared"
    )

    def __repr__(self):
        return f"<Insight id={self.id} type={self.insight_type} priority={self.priority}>"