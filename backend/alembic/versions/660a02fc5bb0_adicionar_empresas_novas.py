"""adicionar_empresas_novas

Revision ID: 660a02fc5bb0
Revises: c07d72cae2a8
Create Date: 2026-05-20 20:02:18.583157

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '660a02fc5bb0'
down_revision: Union[str, None] = 'c07d72cae2a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_COMPANIES = [
    ("banco_bv",      "Banco BV"),
    ("bradesco",      "Bradesco"),
    ("ifood",         "Ifood"),
    ("itau_unibanco", "Itaú Unibanco"),
    ("mercado_livre", "Mercado Livre"),
]

def upgrade() -> None:
    conn = op.get_bind()
    for slug, name in NEW_COMPANIES:
        exists = conn.execute(
            text("SELECT 1 FROM companies WHERE slug = :slug"),
            {"slug": slug},
        ).fetchone()
        if not exists:
            conn.execute(
                text("INSERT INTO companies (slug, name) VALUES (:slug, :name)"),
                {"slug": slug, "name": name},
            )

def downgrade() -> None:
    conn = op.get_bind()
    slugs = [s for s, _ in NEW_COMPANIES]
    conn.execute(
        text("DELETE FROM companies WHERE slug = ANY(:slugs)"),
        {"slugs": slugs},
    )
