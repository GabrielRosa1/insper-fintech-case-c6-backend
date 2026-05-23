"""add_empresas_referenciadas

Revision ID: bea8a2d52a58
Revises: 036c8c1c843a
Create Date: 2026-05-23 14:35:19.336350

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'bea8a2d52a58'
down_revision: Union[str, None] = '036c8c1c843a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insights",
        sa.Column(
            "empresas_referenciadas",
            postgresql.JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_insights_empresas_referenciadas",
        "insights",
        ["empresas_referenciadas"],
        postgresql_using="gin",  # GIN index é ideal para JSONB arrays
    )
 
 
def downgrade() -> None:
    op.drop_index("ix_insights_empresas_referenciadas", table_name="insights")
    op.drop_column("insights", "empresas_referenciadas")
 
