from fastapi import APIRouter, Depends
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

@router.get("/gaps")
def get_gaps(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT d.name, d.slug, d.icon,
               g.gap_severity, g.gap_direction,
               g.gap_description, g.recommendation,
               g.jobs_signal, g.reviews_sentiment_score,
               g.reviews_pct_negative, g.supporting_review_ids
        FROM discourse_reality_gaps g
        JOIN dimensions d ON d.id = g.dimension_id
        WHERE g.company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
          AND g.analysis_version = 'v1'
        ORDER BY g.gap_severity DESC
    """)).fetchall()

    gaps = []
    for row in rows:
        (dim_name, dim_slug, icon, severity, direction,
         description, recommendation, jobs_signal,
         reviews_score, reviews_pct_neg, review_ids) = row
        gaps.append({
            "dimensao": dim_name, "slug": dim_slug, "icon": icon,
            "severidade": severity, "direcao": direction,
            "descricao": description, "recomendacao": recommendation,
            "sinal_vagas": jobs_signal,
            "score_reviews": float(reviews_score) if reviews_score else None,
            "pct_negativo": float(reviews_pct_neg) if reviews_pct_neg else None,
            "supporting_review_ids": safe_loads(review_ids),
        })

    return {"gaps": gaps, "total": len(gaps), "criticos": sum(1 for g in gaps if g["severidade"] >= 4)}