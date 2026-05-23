"""onda3_strategy_tables

Revision ID: 667b4fb7fd0f
Revises: 660a02fc5bb0
Create Date: 2026-05-22 20:30:24.352599

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '667b4fb7fd0f'
down_revision: Union[str, None] = '660a02fc5bb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── insight_actions ───────────────────────────────────────────────────────
    op.create_table(
        "insight_actions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("insight_id", sa.Integer, sa.ForeignKey("insights.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pendente"),
        sa.Column("notas", sa.Text, nullable=True),
        sa.Column("atualizado_por", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_insight_actions_insight_id", "insight_actions", ["insight_id"])
    op.create_index("ix_insight_actions_status", "insight_actions", ["status"])
 
    # Check constraint para status válidos
    op.execute("""
        ALTER TABLE insight_actions
        ADD CONSTRAINT chk_action_status
        CHECK (status IN ('pendente', 'em_andamento', 'concluida', 'descartada'))
    """)
 
    # ── captation_playbooks ───────────────────────────────────────────────────
    op.create_table(
        "captation_playbooks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("insight_id", sa.Integer, sa.ForeignKey("insights.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_company_slug", sa.String(50), nullable=False),
 
        # Persona e contexto
        sa.Column("persona_titulo", sa.String(200), nullable=True),
        sa.Column("persona_descricao", sa.Text, nullable=True),
 
        # Argumentos
        sa.Column("argumentos_ancora", postgresql.JSONB, nullable=True),
        sa.Column("pontos_de_cuidado", postgresql.JSONB, nullable=True),
 
        # Evidências
        sa.Column("quotes_recomendadas", postgresql.JSONB, nullable=True),
        sa.Column("dimensoes_destaque", postgresql.JSONB, nullable=True),
 
        # Outreach
        sa.Column("mensagem_linkedin", sa.Text, nullable=True),
        sa.Column("email_sugerido", sa.Text, nullable=True),
        sa.Column("canais_recomendados", postgresql.JSONB, nullable=True),
 
        # Vagas
        sa.Column("vagas_relevantes", postgresql.JSONB, nullable=True),
 
        # Meta
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("generation_cost", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_captation_playbooks_insight_id", "captation_playbooks", ["insight_id"])
    op.create_index("ix_captation_playbooks_target", "captation_playbooks", ["target_company_slug"])
    op.create_index("ix_captation_playbooks_created_at", "captation_playbooks", ["created_at"])
 
    # ── insights: novos campos para estratégia ────────────────────────────────
    op.add_column("insights", sa.Column("is_active_window", sa.Boolean, server_default="false", nullable=False))
    op.add_column("insights", sa.Column("captation_priority", sa.Integer, nullable=True))  # 1-5, NULL = não é janela
    op.create_index("ix_insights_active_window", "insights", ["is_active_window"])
 
 
def downgrade() -> None:
    op.drop_index("ix_insights_active_window", table_name="insights")
    op.drop_column("insights", "captation_priority")
    op.drop_column("insights", "is_active_window")
 
    op.drop_index("ix_captation_playbooks_created_at", table_name="captation_playbooks")
    op.drop_index("ix_captation_playbooks_target", table_name="captation_playbooks")
    op.drop_index("ix_captation_playbooks_insight_id", table_name="captation_playbooks")
    op.drop_table("captation_playbooks")
 
    op.execute("ALTER TABLE insight_actions DROP CONSTRAINT IF EXISTS chk_action_status")
    op.drop_index("ix_insight_actions_status", table_name="insight_actions")
    op.drop_index("ix_insight_actions_insight_id", table_name="insight_actions")
    op.drop_table("insight_actions")