"""chat_threads_messages

Revision ID: 314e6a2b8a60
Revises: c3375f4b841d
Create Date: 2026-05-17 13:30:33.276320

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '314e6a2b8a60'
down_revision: Union[str, None] = 'c3375f4b841d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── chat_threads ─────────────────────────────────────────────────────────
    # Cada thread representa uma sessão de conversa de um usuário
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.String(36), primary_key=True),          # UUID v4
        sa.Column("title", sa.Text, nullable=True),                 # Auto-gerado da 1ª pergunta
        sa.Column("target_company_id", sa.Integer,
                  sa.ForeignKey("companies.id"), nullable=True),    # Contexto da empresa
        sa.Column("user_identifier", sa.String(255), nullable=True),# Email, user_id, etc.
        sa.Column("metadata", postgresql.JSONB, nullable=True),     # Filtros ativos, contexto extra
        sa.Column("message_count", sa.Integer, default=0),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
    )
 
    op.create_index("ix_chat_threads_user",       "chat_threads", ["user_identifier"])
    op.create_index("ix_chat_threads_company",    "chat_threads", ["target_company_id"])
    op.create_index("ix_chat_threads_created_at", "chat_threads", ["created_at"])
 
    # ── chat_messages ─────────────────────────────────────────────────────────
    # Cada mensagem dentro de um thread
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.String(36),
                  sa.ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),           # "user" | "assistant"
        sa.Column("content", sa.Text, nullable=False),              # Texto da mensagem
        sa.Column("sources", postgresql.JSONB, nullable=True),      # Reviews citadas como evidência
        sa.Column("review_ids_used", postgresql.ARRAY(sa.Integer), nullable=True),  # IDs das reviews
        sa.Column("embedding_query", sa.Text, nullable=True),       # Query usada para RAG
        sa.Column("tokens_used", sa.Integer, nullable=True),        # Tokens consumidos
        sa.Column("model_used", sa.String(100), nullable=True),     # Modelo Claude usado
        sa.Column("latency_ms", sa.Integer, nullable=True),         # Latência da resposta em ms
        sa.Column("feedback", sa.String(20), nullable=True),        # "positive" | "negative" | null
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
    )
 
    op.create_index("ix_chat_messages_thread",     "chat_messages", ["thread_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])
    op.create_index("ix_chat_messages_role",       "chat_messages", ["role"])
 
 
def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")