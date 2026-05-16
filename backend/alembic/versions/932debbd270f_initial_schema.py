"""initial_schema

Revision ID: 932debbd270f
Revises: 
Create Date: 2026-05-16 12:41:24.110022

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '932debbd270f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── pgvector extension ──────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
 
    # ── companies ───────────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("segment", sa.String(50)),
        sa.Column("country", sa.String(10), server_default="BR"),
        sa.Column("is_target", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("logo_url", sa.Text()),
        sa.Column("glassdoor_url", sa.Text()),
        sa.Column("linkedin_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
 
    # ── dimensions ──────────────────────────────────────────────────────
    op.create_table(
        "dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("icon", sa.String(50)),
        sa.Column("display_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("is_core", sa.Boolean(), server_default="true"),
    )
 
    # ── reviews ─────────────────────────────────────────────────────────
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        # Dados originais
        sa.Column("cargo", sa.Text()),
        sa.Column("localizacao", sa.Text()),
        sa.Column("data_review", sa.Date()),
        sa.Column("status_funcionario", sa.String(50)),
        sa.Column("tempo_empresa", sa.String(50)),
        sa.Column("avaliacao_geral", sa.Float()),
        sa.Column("recomendaria", sa.Boolean()),
        sa.Column("aprovacao_ceo", sa.Boolean()),
        sa.Column("perspectiva_negocio", sa.Boolean()),
        sa.Column("titulo_review", sa.Text()),
        sa.Column("pros", sa.Text()),
        sa.Column("contras", sa.Text()),
        sa.Column("conselho_presidencia", sa.Text()),
        # Metadados
        sa.Column("source_file", sa.String(200)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        # Flags de qualidade
        sa.Column("is_event_review", sa.Boolean(), server_default="false"),
        sa.Column("is_duplicate", sa.Boolean(), server_default="false"),
        sa.Column("quality_score", sa.Float()),
        # Análise micro da IA
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.Column("analysis_version", sa.String(20)),
        sa.Column("nivel_senioridade", sa.String(30)),
        sa.Column("area_funcional", sa.String(50)),
        sa.Column("sentimento_geral", sa.String(20)),
        sa.Column("intensidade_emocional", sa.Integer()),
        sa.Column("momento_experiencia", sa.String(20)),
        sa.Column("temas_emergentes", sa.JSON()),
        sa.Column("menciona_concorrentes", sa.JSON()),
        sa.Column("tem_linguagem_saudosismo", sa.Boolean(), server_default="false"),
        sa.Column("tem_linguagem_revolta", sa.Boolean(), server_default="false"),
        sa.Column("tem_linguagem_admiracao", sa.Boolean(), server_default="false"),
        sa.Column("resumo_ia", sa.Text()),
        sa.Column("embedding", Vector(1024)),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
 
    # ── review_dimensions ───────────────────────────────────────────────
    op.create_table(
        "review_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("dimension_id", sa.Integer(), sa.ForeignKey("dimensions.id"), nullable=False),
        sa.Column("analysis_version", sa.String(20)),
        sa.Column("sentiment", sa.String(20), nullable=False),
        sa.Column("intensity", sa.Integer()),
        sa.Column("evidence_quote", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("is_primary", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
 
    # ── jobs ────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("titulo", sa.Text()),
        sa.Column("localizacao", sa.Text()),
        sa.Column("seniority_score", sa.Integer()),
        sa.Column("area", sa.String(50)),
        sa.Column("work_model", sa.String(20), server_default="unknown"),
        sa.Column("has_ml", sa.Boolean(), server_default="false"),
        sa.Column("has_cloud", sa.Boolean(), server_default="false"),
        sa.Column("has_backend", sa.Boolean(), server_default="false"),
        sa.Column("has_data", sa.Boolean(), server_default="false"),
        sa.Column("has_frontend", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
 
    # ── job_skills ──────────────────────────────────────────────────────
    op.create_table(
        "job_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("skill", sa.String(100), nullable=False),
    )
 
    # ── company_events ──────────────────────────────────────────────────
    op.create_table(
        "company_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("descricao", sa.Text()),
        sa.Column("event_type", sa.String(30)),
        sa.Column("data_evento", sa.Date()),
        sa.Column("source", sa.String(30), server_default="auto_detected"),
        sa.Column("sentiment_before", sa.Float()),
        sa.Column("sentiment_after", sa.Float()),
        sa.Column("sentiment_delta", sa.Float()),
        sa.Column("review_volume_delta", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("is_confirmed", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
 
    # ── company_dimension_stats ─────────────────────────────────────────
    op.create_table(
        "company_dimension_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("dimension_id", sa.Integer(), sa.ForeignKey("dimensions.id"), nullable=False),
        sa.Column("analysis_version", sa.String(20)),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("total_mentions", sa.Integer(), server_default="0"),
        sa.Column("positive_count", sa.Integer(), server_default="0"),
        sa.Column("negative_count", sa.Integer(), server_default="0"),
        sa.Column("mixed_count", sa.Integer(), server_default="0"),
        sa.Column("neutral_count", sa.Integer(), server_default="0"),
        sa.Column("sentiment_score", sa.Float()),
        sa.Column("avg_intensity", sa.Float()),
        sa.Column("mention_rate", sa.Float()),
        sa.Column("top_themes", sa.JSON()),
        sa.Column("top_positive_quotes", sa.JSON()),
        sa.Column("top_negative_quotes", sa.JSON()),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
 
    # ── discourse_reality_gaps ──────────────────────────────────────────
    op.create_table(
        "discourse_reality_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("dimension_id", sa.Integer(), sa.ForeignKey("dimensions.id"), nullable=False),
        sa.Column("analysis_version", sa.String(20)),
        sa.Column("jobs_signal", sa.Text()),
        sa.Column("jobs_pct_mentioning", sa.Float()),
        sa.Column("reviews_sentiment_score", sa.Float()),
        sa.Column("reviews_pct_negative", sa.Float()),
        sa.Column("gap_direction", sa.String(30)),
        sa.Column("gap_severity", sa.Integer()),
        sa.Column("gap_description", sa.Text()),
        sa.Column("supporting_job_examples", sa.JSON()),
        sa.Column("supporting_review_ids", sa.JSON()),
        sa.Column("recommendation", sa.Text()),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
 
    # ── insights ────────────────────────────────────────────────────────
    op.create_table(
        "insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("compared_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("analysis_version", sa.String(20)),
        sa.Column("insight_type", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("titulo", sa.String(300), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("headline", sa.String(200)),
        sa.Column("acao_recomendada", sa.Text()),
        sa.Column("acao_prazo", sa.String(50)),
        sa.Column("acao_responsavel", sa.String(100)),
        sa.Column("impacto_score", sa.Integer()),
        sa.Column("esforco_score", sa.Integer()),
        sa.Column("roi_score", sa.Float()),
        sa.Column("supporting_review_ids", sa.JSON()),
        sa.Column("supporting_quotes", sa.JSON()),
        sa.Column("supporting_data", sa.JSON()),
        sa.Column("related_dimension_ids", sa.JSON()),
        sa.Column("is_verified", sa.Boolean(), server_default="false"),
        sa.Column("is_featured", sa.Boolean(), server_default="false"),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
 
    # ── ÍNDICES DE PERFORMANCE ──────────────────────────────────────────
    # Reviews
    op.create_index("ix_reviews_company_id", "reviews", ["company_id"])
    op.create_index("ix_reviews_data_review", "reviews", ["data_review"])
    op.create_index("ix_reviews_avaliacao_geral", "reviews", ["avaliacao_geral"])
    op.create_index("ix_reviews_analysis_version", "reviews", ["analysis_version"])
    op.create_index("ix_reviews_sentimento_geral", "reviews", ["sentimento_geral"])
    op.create_index("ix_reviews_company_date", "reviews", ["company_id", "data_review"])
 
    # ReviewDimensions
    op.create_index("ix_rd_review_id", "review_dimensions", ["review_id"])
    op.create_index("ix_rd_dimension_id", "review_dimensions", ["dimension_id"])
    op.create_index("ix_rd_sentiment", "review_dimensions", ["sentiment"])
    op.create_index("ix_rd_company_dim", "review_dimensions", ["review_id", "dimension_id"])
 
    # Jobs
    op.create_index("ix_jobs_company_id", "jobs", ["company_id"])
    op.create_index("ix_jobs_work_model", "jobs", ["work_model"])
    op.create_index("ix_jobs_area", "jobs", ["area"])
 
    # JobSkills
    op.create_index("ix_job_skills_job_id", "job_skills", ["job_id"])
    op.create_index("ix_job_skills_skill", "job_skills", ["skill"])
 
    # Stats
    op.create_index(
        "ix_stats_company_dim_period",
        "company_dimension_stats",
        ["company_id", "dimension_id", "period"],
        unique=True,
    )
 
    # Insights
    op.create_index("ix_insights_target_company", "insights", ["target_company_id"])
    op.create_index("ix_insights_type", "insights", ["insight_type"])
    op.create_index("ix_insights_priority", "insights", ["priority"])
 
    # Vector index para RAG (IVFFlat — bom para datasets < 100k)
    op.execute("""
        CREATE INDEX ix_reviews_embedding
        ON reviews
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
 
 
def downgrade() -> None:
    op.drop_table("insights")
    op.drop_table("discourse_reality_gaps")
    op.drop_table("company_dimension_stats")
    op.drop_table("company_events")
    op.drop_table("job_skills")
    op.drop_table("jobs")
    op.drop_table("review_dimensions")
    op.drop_table("reviews")
    op.drop_table("dimensions")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS vector")