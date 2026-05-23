from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db

router = APIRouter(tags=["timeline"])

@router.get("/timeline")
def get_timeline(db: Session = Depends(get_db)):
    # Sentimento mensal por empresa (todas as 7)
    rows = db.execute(text("""
        SELECT c.slug, c.name, c.is_target,
            EXTRACT(YEAR FROM r.data_review)::int as yr,
            EXTRACT(MONTH FROM r.data_review)::int as mo,
            SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) as pos,
            SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) as neg,
            SUM(CASE WHEN r.sentimento_geral = 'misto'    THEN 1 ELSE 0 END) as mix,
            COUNT(*) as total
        FROM reviews r JOIN companies c ON c.id = r.company_id
        WHERE r.data_review IS NOT NULL
          AND r.sentimento_geral IS NOT NULL
          AND r.is_event_review = false
          AND r.analysis_version IS NOT NULL
          AND r.data_review >= '2022-01-01'
          AND r.data_review <= CURRENT_DATE
          AND c.is_active = true
        GROUP BY c.slug, c.name, c.is_target, yr, mo
        HAVING COUNT(*) >= 2
        ORDER BY c.slug, yr, mo
    """)).fetchall()

    series: dict = {}
    for slug, name, is_target, yr, mo, pos, neg, mix, total in rows:
        if slug not in series:
            series[slug] = {
                "slug":      slug,
                "name":      name,
                "is_target": is_target,
                "points":    [],
            }
        score = round(((pos * 1.0 + mix * 0.5) / total) * 10, 2) if total else 5.0
        series[slug]["points"].append({
            "label": f"{yr}-{mo:02d}",
            "score": score,
            "total": total,
            "pos":   pos,
            "neg":   neg,
        })

    # Eventos confirmados ou manuais, sem datas absurdas (corta 2028 fantasma)
    events = db.execute(text("""
        SELECT ce.nome, ce.event_type, ce.data_evento,
               ce.sentiment_delta, ce.is_confirmed, ce.source,
               c.slug as company_slug, c.name as company_name
        FROM company_events ce
        JOIN companies c ON c.id = ce.company_id
        WHERE (ce.is_confirmed = true OR ce.source = 'manual')
          AND ce.data_evento <= CURRENT_DATE
          AND ce.data_evento >= '2022-01-01'
        ORDER BY ce.data_evento
    """)).fetchall()

    events_list = []
    for nome, etype, data_ev, delta, confirmed, source, slug, co_name in events:
        events_list.append({
            "nome":         nome,
            "tipo":         etype,
            "data":         str(data_ev)[:7] if data_ev else None,
            "delta":        float(delta) if delta else None,
            "empresa_slug": slug,
            "empresa_nome": co_name,
            "source":       source,
        })

    # Empresas disponíveis (para o seletor de toggle)
    companies_info = [
        {"slug": s["slug"], "name": s["name"], "is_target": s["is_target"], "points": len(s["points"])}
        for s in series.values()
    ]

    return {
        "series":    list(series.values()),
        "events":    events_list,
        "companies": companies_info,
    }
