from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
import json

router = APIRouter(tags=["overview"])

def safe_loads(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []

@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    # Métricas gerais por empresa
    companies = db.execute(text("""
        SELECT c.slug, c.name,
            COUNT(r.id) as total_reviews,
            ROUND(AVG(r.avaliacao_geral)::numeric, 2) as avg_nota,
            SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) as positivo,
            SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) as negativo,
            SUM(CASE WHEN r.recomendaria = true THEN 1 ELSE 0 END) as recomendaria,
            SUM(CASE WHEN r.aprovacao_ceo = true THEN 1 ELSE 0 END) as aprova_ceo
        FROM companies c
        LEFT JOIN reviews r ON r.company_id = c.id
            AND r.is_event_review = false
            AND r.analysis_version IS NOT NULL
        GROUP BY c.slug, c.name, c.is_target
        ORDER BY c.is_target DESC
    """)).fetchall()

    result = []
    for row in companies:
        slug, name, total, avg_nota, pos, neg, rec, ceo = row
        result.append({
            "slug": slug,
            "name": name,
            "total_reviews": total,
            "avg_nota": float(avg_nota) if avg_nota else 0,
            "pct_positivo": round((pos or 0) / total * 100, 1) if total else 0,
            "pct_negativo": round((neg or 0) / total * 100, 1) if total else 0,
            "pct_recomendaria": round((rec or 0) / total * 100, 1) if total else 0,
            "pct_aprova_ceo": round((ceo or 0) / total * 100, 1) if total else 0,
        })

    # Scorecard por dimensão
    scorecard = db.execute(text("""
        SELECT d.slug, d.name, d.icon,
            s1.sentiment_score as c6_score, s1.total_mentions as c6_mencoes,
            s2.sentiment_score as nu_score,  s2.total_mentions as nu_mencoes,
            s1.top_negative_quotes as c6_neg_quotes,
            s1.top_positive_quotes as c6_pos_quotes
        FROM dimensions d
        LEFT JOIN company_dimension_stats s1 ON s1.dimension_id = d.id
            AND s1.period = 'all' AND s1.analysis_version = 'v1'
            AND s1.company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
        LEFT JOIN company_dimension_stats s2 ON s2.dimension_id = d.id
            AND s2.period = 'all' AND s2.analysis_version = 'v1'
            AND s2.company_id = (SELECT id FROM companies WHERE slug = 'nubank')
        WHERE d.is_active = true
        ORDER BY d.display_order
    """)).fetchall()

    dimensions = []
    for row in scorecard:
        slug, name, icon, c6_s, c6_m, nu_s, nu_m, c6_nq, c6_pq = row
        c6_score = float(c6_s) if c6_s else 0
        nu_score  = float(nu_s)  if nu_s  else 0
        diff = c6_score - nu_score
        vantagem = "c6" if diff > 0.5 else ("nubank" if diff < -0.5 else "empate")

        neg_q = safe_loads(c6_nq)
        pos_q = safe_loads(c6_pq)

        dimensions.append({
            "slug": slug, "name": name, "icon": icon,
            "c6_score": c6_score,   "c6_mencoes": c6_m or 0,
            "nu_score":  nu_score,   "nu_mencoes":  nu_m or 0,
            "vantagem": vantagem,    "diff": round(abs(diff), 1),
            "top_negative_quote": neg_q[0]["quote"] if neg_q else "",
            "top_positive_quote": pos_q[0]["quote"] if pos_q else "",
        })

    # Temas emergentes top C6
    temas_rows = db.execute(text("""
        SELECT temas_emergentes FROM reviews
        WHERE company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
          AND is_event_review = false AND temas_emergentes IS NOT NULL
    """)).fetchall()
    from collections import Counter
    all_temas = []
    for (t,) in temas_rows:
        all_temas.extend(safe_loads(t))
    top_temas = [{"tema": t, "count": c} for t, c in Counter(all_temas).most_common(10)]

    # Linguagem emocional
    emo = db.execute(text("""
        SELECT c.slug,
            SUM(CASE WHEN r.tem_linguagem_saudosismo THEN 1 ELSE 0 END) as saudosismo,
            SUM(CASE WHEN r.tem_linguagem_revolta THEN 1 ELSE 0 END) as revolta,
            SUM(CASE WHEN r.tem_linguagem_admiracao THEN 1 ELSE 0 END) as admiracao,
            COUNT(*) as total
        FROM reviews r JOIN companies c ON c.id = r.company_id
        WHERE r.is_event_review = false AND r.analysis_version IS NOT NULL
        GROUP BY c.slug
    """)).fetchall()
    emocoes = {row[0]: {"saudosismo": row[1], "revolta": row[2], "admiracao": row[3], "total": row[4]} for row in emo}

    return {
        "companies": result,
        "scorecard": dimensions,
        "top_temas_c6": top_temas,
        "emocoes": emocoes,
    }