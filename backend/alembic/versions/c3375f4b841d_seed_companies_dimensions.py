"""seed_companies_dimensions

Revision ID: c3375f4b841d
Revises: 932debbd270f
Create Date: 2026-05-16 12:44:25.387238

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision: str = 'c3375f4b841d'
down_revision: Union[str, None] = '932debbd270f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Companies ───────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO companies (slug, name, display_name, segment, country, is_target, is_active)
        VALUES
        (
            'c6_bank',
            'C6 Bank',
            'C6 Bank',
            'fintech',
            'BR',
            true,
            true
        ),
        (
            'nubank',
            'Nubank',
            'Nubank',
            'fintech',
            'BR',
            false,
            true
        )
    """)
 
    # ── Dimensions ──────────────────────────────────────────────────────
    # Cada dimensão tem uma description usada no prompt da IA
    op.execute("""
        INSERT INTO dimensions (slug, name, description, icon, display_order, is_active, is_core)
        VALUES
        (
            'lideranca',
            'Liderança',
            'Qualidade da gestão direta e alta liderança: preparo, transparência, microgestão, feedback, favoritismo, decisões top-down',
            'users',
            1,
            true,
            true
        ),
        (
            'cultura',
            'Cultura',
            'Valores da empresa na prática, ambiente de trabalho, psicologia segura, autenticidade, diferença entre discurso e realidade',
            'heart',
            2,
            true,
            true
        ),
        (
            'salario_beneficios',
            'Salário e Benefícios',
            'Remuneração, salário base, PLR, bônus, RSUs/ações, vale-refeição, vale-alimentação, plano de saúde, benefícios bancários',
            'dollar-sign',
            3,
            true,
            true
        ),
        (
            'modelo_trabalho',
            'Modelo de Trabalho',
            'Presencial vs remoto vs híbrido, flexibilidade de horário, política de home office, retorno ao escritório',
            'map-pin',
            4,
            true,
            true
        ),
        (
            'crescimento',
            'Crescimento e Carreira',
            'Plano de carreira, promoções, meritocracia vs politicagem, aprendizado, mobilidade interna, reconhecimento',
            'trending-up',
            5,
            true,
            true
        ),
        (
            'saude_mental',
            'Saúde Mental e WLB',
            'Burnout, pressão excessiva, carga de trabalho, work-life balance, síndrome do impostor, adoecimento',
            'activity',
            6,
            true,
            true
        ),
        (
            'diversidade',
            'Diversidade e Inclusão',
            'D&I na prática vs discurso, representatividade em cargos de liderança, racismo, machismo, acessibilidade, LGBTfobia',
            'globe',
            7,
            true,
            true
        ),
        (
            'tech_stack',
            'Stack Técnica',
            'Tecnologias utilizadas, qualidade do ambiente de engenharia, linguagens, ferramentas, dívida técnica, inovação técnica',
            'code',
            8,
            true,
            true
        ),
        (
            'proposito',
            'Propósito e Impacto',
            'Senso de missão, impacto real do trabalho, alinhamento com valores pessoais, orgulho de trabalhar na empresa',
            'star',
            9,
            true,
            true
        )
    """)
 
 
def downgrade() -> None:
    op.execute("DELETE FROM dimensions")
    op.execute("DELETE FROM companies")