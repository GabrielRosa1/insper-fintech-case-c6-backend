from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
import json

router = APIRouter(tags=["insights"])

def safe_loads(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []

@router.get("/insights")
def get_insights(
    tipo: str = Query(None),
    prioridade: str = Query(None),
    db: Session = Depends(get_db)
):
    where = ["i.target_company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')"]
    params = {}
    if tipo:
        where.append("i.insight_type = :tipo")
        params["tipo"] = tipo
    if prioridade:
        where.append("i.priority = :prioridade")
        params["prioridade"] = prioridade

    rows = db.execute(text(f"""
        SELECT i.id, i.insight_type, i.priority, i.titulo, i.headline,
               i.descricao, i.acao_recomendada, i.acao_prazo, i.acao_responsavel,
               i.impacto_score, i.esforco_score, i.roi_score,
               i.supporting_quotes, i.is_featured,
               co.name as empresa_comparada
        FROM insights i
        LEFT JOIN companies co ON co.id = i.compared_company_id
        WHERE {' AND '.join(where)}
        ORDER BY
            CASE i.priority
                WHEN 'critica' THEN 0 WHEN 'alta' THEN 1
                WHEN 'media' THEN 2 ELSE 3 END,
            i.roi_score DESC
    """), params).fetchall()

    insights = []
    for row in rows:
        (id_, tipo_, prioridade_, titulo, headline, descricao,
         acao, prazo, responsavel, impacto, esforco, roi,
         quotes_raw, featured, empresa_comp) = row
        insights.append({
            "id": id_, "tipo": tipo_, "prioridade": prioridade_,
            "titulo": titulo, "headline": headline, "descricao": descricao,
            "acao_recomendada": acao, "acao_prazo": prazo,
            "acao_responsavel": responsavel,
            "impacto_score": impacto, "esforco_score": esforco,
            "roi_score": float(roi) if roi else 0,
            "supporting_quotes": safe_loads(quotes_raw)[:2],
            "is_featured": featured,
            "empresa_comparada": empresa_comp,
        })

    # Resumo por prioridade
    summary = {"critica": 0, "alta": 0, "media": 0, "baixa": 0}
    for ins in insights:
        summary[ins["prioridade"]] = summary.get(ins["prioridade"], 0) + 1

    return {"insights": insights, "summary": summary, "total": len(insights)}