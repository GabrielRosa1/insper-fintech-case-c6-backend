from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from collections import Counter
import json

router = APIRouter(tags=["overview"])

# Empresas com amostragem estratificada — usar só reviews chronological
STRATIFIED_SLUGS = ("c6_bank", "nubank")

def safe_loads(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []

@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    # ── Métricas gerais por empresa ───────────────────────────────────────────
    # FIX: filtra sample_type = 'chronological' para C6/Nubank
    companies_rows = db.execute(text("""
        SELECT c.slug, c.name, c.is_target,
            COUNT(r.id) as total_reviews,
            ROUND(AVG(r.avaliacao_geral)::numeric, 2) as avg_nota,
            SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) as positivo,
            SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) as negativo,
            SUM(CASE WHEN r.sentimento_geral = 'misto'    THEN 1 ELSE 0 END) as misto,
            SUM(CASE WHEN r.recomendaria = true THEN 1 ELSE 0 END) as recomendaria,
            SUM(CASE WHEN r.aprovacao_ceo = true THEN 1 ELSE 0 END) as aprova_ceo
        FROM companies c
        LEFT JOIN reviews r ON r.company_id = c.id
            AND r.is_event_review = false
            AND r.analysis_version IS NOT NULL
            AND (
                c.slug NOT IN :slugs
                OR r.sample_type = 'chronological'
            )
        WHERE c.is_active = true
        GROUP BY c.slug, c.name, c.is_target
        ORDER BY c.is_target DESC, avg_nota DESC NULLS LAST
    """), {"slugs": STRATIFIED_SLUGS}).fetchall()

    companies = []
    for row in companies_rows:
        slug, name, is_target, total, avg_nota, pos, neg, mix, rec, ceo = row
        sentiment_score = 0
        if total:
            sentiment_score = round(((pos or 0) * 1.0 + (mix or 0) * 0.5) / total * 10, 1)

        companies.append({
            "slug":             slug,
            "name":             name,
            "is_target":        is_target,
            "total_reviews":    total or 0,
            "avg_nota":         float(avg_nota) if avg_nota else 0,
            "sentiment_score":  sentiment_score,
            "pct_positivo":     round((pos or 0) / total * 100, 1) if total else 0,
            "pct_negativo":     round((neg or 0) / total * 100, 1) if total else 0,
            "pct_misto":        round((mix or 0) / total * 100, 1) if total else 0,
            "pct_recomendaria": round((rec or 0) / total * 100, 1) if total else 0,
            "pct_aprova_ceo":   round((ceo or 0) / total * 100, 1) if total else 0,
        })

    c6 = next((c for c in companies if c["slug"] == "c6_bank"), None)

    # ── Rankings de mercado por dimensão (lê de company_dimension_stats v2) ───
    # Sem alteração — v2 já tem os dados corretos
    dimension_rows = db.execute(text("""
        SELECT d.slug, d.name, d.icon, d.display_order,
               c.slug as co_slug, c.name as co_name,
               s.sentiment_score, s.total_mentions,
               s.positive_count, s.negative_count,
               s.top_negative_quotes, s.top_positive_quotes
        FROM company_dimension_stats s
        JOIN dimensions d ON d.id = s.dimension_id
        JOIN companies   c ON c.id = s.company_id
        WHERE s.period = 'all' AND s.analysis_version = 'v2'
          AND d.is_active = true AND c.is_active = true
          AND s.total_mentions >= 3
        ORDER BY d.display_order, s.sentiment_score DESC
    """)).fetchall()

    dims_map: dict = {}
    for row in dimension_rows:
        (d_slug, d_name, d_icon, d_order, co_slug, co_name,
         score, mentions, pos, neg, neg_q, pos_q) = row

        if d_slug not in dims_map:
            dims_map[d_slug] = {
                "slug": d_slug, "name": d_name,
                "icon": d_icon, "order": d_order,
                "ranking": [],
            }

        dims_map[d_slug]["ranking"].append({
            "company_slug":     co_slug,
            "company_name":     co_name,
            "score":            float(score) if score else 0,
            "mentions":         mentions,
            "pct_negativo":     round((neg or 0) / mentions * 100, 1) if mentions else 0,
            "pct_positivo":     round((pos or 0) / mentions * 100, 1) if mentions else 0,
            "top_negative_quote": (safe_loads(neg_q)[0]["quote"] if safe_loads(neg_q) else ""),
            "top_positive_quote": (safe_loads(pos_q)[0]["quote"] if safe_loads(pos_q) else ""),
        })

    dimensions = []
    c6_positions = []

    for d_slug, d_data in sorted(dims_map.items(), key=lambda x: x[1]["order"]):
        ranking        = d_data["ranking"]
        total_companies = len(ranking)

        c6_position = None
        c6_score    = 0
        c6_mentions = 0
        for idx, r in enumerate(ranking):
            if r["company_slug"] == "c6_bank":
                c6_position = idx + 1
                c6_score    = r["score"]
                c6_mentions = r["mentions"]
                break

        market_scores = [r["score"] for r in ranking]
        market_avg    = round(sum(market_scores) / len(market_scores), 1) if market_scores else 0
        leader        = ranking[0]  if ranking else None
        worst         = ranking[-1] if ranking else None

        dimensions.append({
            "slug":            d_slug,
            "name":            d_data["name"],
            "icon":            d_data["icon"],
            "ranking":         ranking,
            "c6_position":     c6_position,
            "c6_score":        c6_score,
            "c6_mentions":     c6_mentions,
            "total_companies": total_companies,
            "market_avg":      market_avg,
            "leader": {"slug": leader["company_slug"], "name": leader["company_name"], "score": leader["score"]} if leader else None,
            "worst":  {"slug": worst["company_slug"],  "name": worst["company_name"],  "score": worst["score"]}  if worst  else None,
            "diff_to_leader": round(c6_score - leader["score"], 1) if (leader and c6_position) else None,
            "diff_to_market": round(c6_score - market_avg, 1)      if c6_position              else None,
        })

        if c6_position:
            c6_positions.append(c6_position)

    # ── Ranking geral do C6 (por sentiment_score) ─────────────────────────────
    sorted_by_sentiment = sorted(companies, key=lambda x: -x["sentiment_score"])
    c6_overall_rank = next((i+1 for i, c in enumerate(sorted_by_sentiment) if c["slug"] == "c6_bank"), None)
    total_co = len(companies)

    leader_overall = sorted_by_sentiment[0] if sorted_by_sentiment else None
    c6_better_than = [c for c in sorted_by_sentiment if c["slug"] != "c6_bank" and c6 and c["sentiment_score"] < c6["sentiment_score"]]
    c6_worse_than  = [c for c in sorted_by_sentiment if c["slug"] != "c6_bank" and c6 and c["sentiment_score"] > c6["sentiment_score"]]

    # ── Top temas emergentes do C6 ────────────────────────────────────────────
    # FIX: filtra sample_type = 'chronological'
    temas_rows = db.execute(text("""
        SELECT r.temas_emergentes FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE c.slug = 'c6_bank'
          AND r.is_event_review = false
          AND r.temas_emergentes IS NOT NULL
          AND r.sample_type = 'chronological'
    """)).fetchall()
    all_temas = []
    for (t,) in temas_rows:
        all_temas.extend(safe_loads(t))
    top_temas = [{"tema": t, "count": c} for t, c in Counter(all_temas).most_common(10)]

    # ── Linguagem emocional por empresa ───────────────────────────────────────
    # FIX: filtra sample_type = 'chronological' para C6/Nubank
    emo_rows = db.execute(text("""
        SELECT c.slug,
            SUM(CASE WHEN r.tem_linguagem_saudosismo THEN 1 ELSE 0 END) as saudosismo,
            SUM(CASE WHEN r.tem_linguagem_revolta    THEN 1 ELSE 0 END) as revolta,
            SUM(CASE WHEN r.tem_linguagem_admiracao  THEN 1 ELSE 0 END) as admiracao,
            COUNT(*) as total
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.is_event_review = false
          AND r.analysis_version IS NOT NULL
          AND (
              c.slug NOT IN :slugs
              OR r.sample_type = 'chronological'
          )
        GROUP BY c.slug
    """), {"slugs": STRATIFIED_SLUGS}).fetchall()
    emocoes = {
        row[0]: {"saudosismo": row[1], "revolta": row[2], "admiracao": row[3], "total": row[4]}
        for row in emo_rows
    }

    total_reviews_all = sum(c["total_reviews"] for c in companies)

    return {
        "companies":    companies,
        "dimensions":   dimensions,
        "top_temas_c6": top_temas,
        "emocoes":      emocoes,
        "market": {
            "total_reviews":   total_reviews_all,
            "total_companies": total_co,
            "c6_overall_rank": c6_overall_rank,
            "leader_overall":  leader_overall,
            "c6_better_than":  len(c6_better_than),
            "c6_worse_than":   len(c6_worse_than),
            "c6_avg_position": round(sum(c6_positions) / len(c6_positions), 1) if c6_positions else None,
        },
    }