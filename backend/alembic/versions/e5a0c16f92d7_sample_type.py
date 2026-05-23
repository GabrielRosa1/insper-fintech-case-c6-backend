"""sample_type

Revision ID: e5a0c16f92d7
Revises: 667b4fb7fd0f
Create Date: 2026-05-22 21:52:10.455189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a0c16f92d7'
down_revision: Union[str, None] = '667b4fb7fd0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adiciona coluna com default 'chronological'
    op.add_column(
        "reviews",
        sa.Column(
            "sample_type",
            sa.String(20),
            nullable=False,
            server_default="chronological",
        ),
    )
 
    op.create_index("ix_reviews_sample_type", "reviews", ["sample_type"])
 
    # Check constraint para valores válidos
    op.execute("""
        ALTER TABLE reviews
        ADD CONSTRAINT chk_reviews_sample_type
        CHECK (sample_type IN ('chronological', 'stratified'))
    """)
 
    # IMPORTANTE: marca todas as reviews ATUAIS do C6 e Nubank como stratified,
    # pois foram coletadas com amostragem por nota (100 de cada estrela).
    # As outras 5 empresas já eram cronológicas — ficam como 'chronological'.
    op.execute("""
        UPDATE reviews
        SET sample_type = 'stratified'
        WHERE company_id IN (
            SELECT id FROM companies
            WHERE slug IN ('c6_bank', 'nubank')
        )
    """)
 
 
def downgrade() -> None:
    op.execute(
        "ALTER TABLE reviews DROP CONSTRAINT IF EXISTS chk_reviews_sample_type"
    )
    op.drop_index("ix_reviews_sample_type", table_name="reviews")
    op.drop_column("reviews", "sample_type")