"""unique_constraint

Revision ID: 036c8c1c843a
Revises: e5a0c16f92d7
Create Date: 2026-05-23 14:26:51.842471

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '036c8c1c843a'
down_revision: Union[str, None] = 'e5a0c16f92d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove o constraint atual (sem analysis_version)
    op.execute("""
        ALTER TABLE company_dimension_stats
        DROP CONSTRAINT IF EXISTS ix_stats_company_dim_period
    """)
 
    # Remove também se for um index (pode ser criado como index, não constraint)
    op.execute("""
        DROP INDEX IF EXISTS ix_stats_company_dim_period
    """)
 
    # Recria incluindo analysis_version
    op.execute("""
        CREATE UNIQUE INDEX ix_stats_company_dim_period_version
        ON company_dimension_stats (company_id, dimension_id, period, analysis_version)
    """)
 
 
def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_stats_company_dim_period_version")
 
    # Restaura o original (só funciona se não houver dados duplicados)
    op.execute("""
        CREATE UNIQUE INDEX ix_stats_company_dim_period
        ON company_dimension_stats (company_id, dimension_id, period)
    """)
