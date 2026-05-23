from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
import json

router = APIRouter(tags=["gaps"])

def safe_loads(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []

# Usa v2 se existir para a empresa, senão cai em v1
# Isso garante que gaps apareçam mesmo antes de rodar 06_gap_analysis com v2
def _best_version(db: Session, slug: str) -> str:
    count = db.execute(text("""
        SELECT COUNT(*) FROM discourse_reality_gaps g
        JOIN companies c ON c.id = g.company_id
        WHERE c.slug = :slug AND g.analysis_version = 'v2'
    """), {"slug": slug}).scalar()
    return "v2" if count else "v1"

@router.get("/gaps")
def get_gaps(
    empresa: str = Query("c6_bank", description="slug da empresa"),
    db: Session = Depends(get_db),
):
    version = _best_version(db, empresa)

    rows = db.execute(text("""
        SELECT d.name, d.slug, d.icon,
               g.gap_severity, g.gap_direction,
               g.gap_description, g.recommendation,
               g.jobs_signal, g.reviews_sentiment_score,
               g.reviews_pct_negative, g.supporting_review_ids,
               c.name as empresa_nome, c.slug as empresa_slug
        FROM discourse_reality_gaps g
        JOIN dimensions d ON d.id = g.dimension_id
        JOIN companies  c ON c.id = g.company_id
        WHERE c.slug = :slug
          AND g.analysis_version = :version
        ORDER BY g.gap_severity DESC
    """), {"slug": empresa, "version": version}).fetchall()

    gaps = []
    for row in rows:
        (dim_name, dim_slug, icon, severity, direction,
         description, recommendation, jobs_signal,
         reviews_score, reviews_pct_neg, review_ids,
         empresa_nome, empresa_slug) = row
        gaps.append({
            "dimensao":              dim_name,
            "slug":                  dim_slug,
            "icon":                  icon,
            "severidade":            severity,
            "direcao":               direction,
            "descricao":             description,
            "recomendacao":          recommendation,
            "sinal_vagas":           jobs_signal,
            "score_reviews":         float(reviews_score) if reviews_score else None,
            "pct_negativo":          float(reviews_pct_neg) if reviews_pct_neg else None,
            "supporting_review_ids": safe_loads(review_ids),
            "empresa":               empresa_nome,
            "empresa_slug":          empresa_slug,
        })

    # Resumo por empresa — usa a melhor versão disponível para cada uma
    summary_rows = db.execute(text("""
        SELECT c.slug, c.name, c.is_target,
               COUNT(*) as total_gaps,
               SUM(CASE WHEN g.gap_severity >= 4 THEN 1 ELSE 0 END) as criticos
        FROM discourse_reality_gaps g
        JOIN companies c ON c.id = g.company_id
        WHERE c.is_active = true
          AND g.analysis_version = (
              SELECT CASE
                WHEN EXISTS (
                    SELECT 1 FROM discourse_reality_gaps g2
                    WHERE g2.company_id = c.id AND g2.analysis_version = 'v2'
                ) THEN 'v2'
                ELSE 'v1'
              END
          )
        GROUP BY c.slug, c.name, c.is_target
        ORDER BY c.is_target DESC, c.name
    """)).fetchall()

    companies_summary = [
        {"slug": r[0], "name": r[1], "is_target": r[2], "total": r[3], "criticos": r[4]}
        for r in summary_rows
    ]

    return {
        "gaps":          gaps,
        "total":         len(gaps),
        "criticos":      sum(1 for g in gaps if g["severidade"] >= 4),
        "altos":         sum(1 for g in gaps if g["severidade"] == 4),
        "empresa_atual": empresa,
        "companies":     companies_summary,
        "_version_used": version,  # debug: mostra qual versão foi usada
    }