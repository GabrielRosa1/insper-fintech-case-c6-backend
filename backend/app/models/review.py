from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    Date, DateTime, ForeignKey, JSON, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base
import enum


class SentimentEnum(str, enum.Enum):
    positivo = "positivo"
    negativo = "negativo"
    misto = "misto"
    neutro = "neutro"


class MomentoEnum(str, enum.Enum):
    inicio = "inicio"       # < 6 meses
    meio = "meio"           # 6 meses - 3 anos
    saida = "saida"         # ex-funcionário
    longo_prazo = "longo_prazo"  # > 3 anos


class Review(Base):
    """
    Review bruta do Glassdoor + análise micro gerada pela IA.
    Cada review pode ter N dimensões associadas via ReviewDimension.
    embedding armazena vector(1024) para RAG com Anthropic.
    """
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)

    # --- Chave estrangeira ---
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # --- Dados originais do Glassdoor ---
    cargo = Column(Text)
    localizacao = Column(Text)
    data_review = Column(Date, index=True)
    status_funcionario = Column(String(50))    # "Funcionário(a) atual" | "Ex-funcionário(a)"
    tempo_empresa = Column(String(50))
    avaliacao_geral = Column(Float)
    recomendaria = Column(Boolean)
    aprovacao_ceo = Column(Boolean)
    perspectiva_negocio = Column(Boolean)
    titulo_review = Column(Text)
    pros = Column(Text)
    contras = Column(Text)
    conselho_presidencia = Column(Text)

    # --- Metadados de origem ---
    source_file = Column(String(200))
    processed_at = Column(DateTime(timezone=True))

    # --- Flags de qualidade ---
    is_event_review = Column(Boolean, default=False)  # Reviews de eventos (foto LinkedIn etc.)
    is_duplicate = Column(Boolean, default=False)
    quality_score = Column(Float)  # 0-1, calculado pelo pipeline

    # --- Análise micro da IA ---
    analyzed_at = Column(DateTime(timezone=True))
    analysis_version = Column(String(20), index=True)  # "v1", "v2"...

    # Perfil inferido
    nivel_senioridade = Column(String(30))   # "junior", "pleno", "senior", "lideranca"
    area_funcional = Column(String(50))      # "engenharia", "produto", "atendimento"...

    # Sentimento geral
    sentimento_geral = Column(Enum(SentimentEnum))
    intensidade_emocional = Column(Integer)  # 1-10

    # Momento da experiência
    momento_experiencia = Column(Enum(MomentoEnum))

    # Temas emergentes detectados pela IA (não pré-definidos)
    temas_emergentes = Column(JSON)          # ["burnout", "rto", "favoritismo", ...]

    # Menções a concorrentes (cruzamento inteligência competitiva)
    menciona_concorrentes = Column(JSON)     # [{"empresa": "Nubank", "contexto": "comparação salarial", "sentimento": "positivo"}]

    # Linguagem emocional
    tem_linguagem_saudosismo = Column(Boolean, default=False)  # "já foi bom", "era incrível"
    tem_linguagem_revolta = Column(Boolean, default=False)     # "absurdo", "inadmissível"
    tem_linguagem_admiracao = Column(Boolean, default=False)   # "melhor empresa"

    # Resumo gerado pela IA
    resumo_ia = Column(Text)  # 2-3 linhas que capturam a essência da review

    # Embedding para RAG
    embedding = Column(Vector(1024))

    # --- Timestamps ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relationships ---
    company = relationship("Company", back_populates="reviews")
    dimensions = relationship("ReviewDimension", back_populates="review", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Review id={self.id} company={self.company_id} nota={self.avaliacao_geral}>"

    @property
    def texto_completo(self) -> str:
        """Concatena pros + contras + conselho para embedding e análise."""
        partes = []
        if self.titulo_review:
            partes.append(f"Título: {self.titulo_review}")
        if self.pros:
            partes.append(f"Pontos positivos: {self.pros}")
        if self.contras:
            partes.append(f"Pontos negativos: {self.contras}")
        if self.conselho_presidencia:
            partes.append(f"Conselho à presidência: {self.conselho_presidencia}")
        return "\n\n".join(partes)