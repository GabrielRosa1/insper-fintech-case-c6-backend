"""
PDF Executive Report — Gerado server-side via xhtml2pdf

Template HTML+CSS profissional para impressão.
Inclui: capa, panorama, scorecard, janelas de captação, ações em andamento.

Instalação necessária (puro Python, sem dependências de sistema):
    pip install xhtml2pdf jinja2

Funciona em Windows, Linux e macOS sem instalar GTK/Pango/Cairo.
"""
import io
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text

from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def safe_loads(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []


def _gather_report_data(db: Session) -> dict:
    """Reúne todos os dados necessários para o PDF."""

    # Companies
    companies = db.execute(text("""
        SELECT c.slug, c.name, c.is_target,
            COUNT(r.id) as total_reviews,
            ROUND(AVG(r.avaliacao_geral)::numeric, 2) as avg_nota,
            SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) as pos,
            SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) as neg,
            SUM(CASE WHEN r.sentimento_geral = 'misto'    THEN 1 ELSE 0 END) as mix
        FROM companies c
        LEFT JOIN reviews r ON r.company_id = c.id
            AND r.is_event_review = false AND r.analysis_version IS NOT NULL
        WHERE c.is_active = true
        GROUP BY c.slug, c.name, c.is_target
        ORDER BY c.is_target DESC
    """)).fetchall()

    company_data = []
    for slug, name, is_target, total, avg_nota, pos, neg, mix in companies:
        if total:
            score = round(((pos or 0) * 1.0 + (mix or 0) * 0.5) / total * 10, 1)
        else:
            score = 0
        company_data.append({
            "slug": slug, "name": name, "is_target": is_target,
            "total_reviews": total or 0,
            "avg_nota": float(avg_nota) if avg_nota else 0,
            "sentiment_score": score,
            "pct_positivo": round((pos or 0) / total * 100, 1) if total else 0,
            "pct_negativo": round((neg or 0) / total * 100, 1) if total else 0,
        })

    # Ranking geral
    ranked = sorted(company_data, key=lambda x: -x["sentiment_score"])
    c6 = next((c for c in ranked if c["slug"] == "c6_bank"), None)
    c6_rank = next((i+1 for i, c in enumerate(ranked) if c["slug"] == "c6_bank"), None)

    # Dimensões
    dim_rows = db.execute(text("""
        SELECT d.slug, d.name, d.display_order,
               c.slug as co_slug, c.name as co_name,
               s.sentiment_score, s.total_mentions
        FROM company_dimension_stats s
        JOIN dimensions d ON d.id = s.dimension_id
        JOIN companies   c ON c.id = s.company_id
        WHERE s.period = 'all' AND s.analysis_version = 'v1'
          AND d.is_active = true AND c.is_active = true
          AND s.total_mentions >= 3
        ORDER BY d.display_order, s.sentiment_score DESC
    """)).fetchall()

    dims_map = {}
    for d_slug, d_name, d_order, co_slug, co_name, score, mentions in dim_rows:
        if d_slug not in dims_map:
            dims_map[d_slug] = {"name": d_name, "order": d_order, "ranking": []}
        dims_map[d_slug]["ranking"].append({
            "slug": co_slug, "name": co_name,
            "score": float(score) if score else 0,
            "mentions": mentions,
        })

    dimensions = []
    for d_slug, d in sorted(dims_map.items(), key=lambda x: x[1]["order"]):
        ranking = d["ranking"]
        c6_entry = next((r for r in ranking if r["slug"] == "c6_bank"), None)
        c6_pos = next((i+1 for i, r in enumerate(ranking) if r["slug"] == "c6_bank"), None)
        leader = ranking[0] if ranking else None
        dimensions.append({
            "name": d["name"],
            "c6_score": c6_entry["score"] if c6_entry else 0,
            "c6_position": c6_pos,
            "total": len(ranking),
            "leader_name": leader["name"] if leader else "—",
            "leader_score": leader["score"] if leader else 0,
            "ranking": ranking,
            "is_c6_leader": leader and leader["slug"] == "c6_bank",
            "is_c6_last":   c6_pos == len(ranking) if c6_pos else False,
        })

    # Insights críticos
    insights = db.execute(text("""
        SELECT i.id, i.titulo, i.headline, i.descricao,
               i.acao_recomendada, i.acao_prazo,
               i.priority, i.impacto_score, i.esforco_score, i.roi_score,
               i.insight_type,
               COALESCE(ia.status, 'pendente') as status
        FROM insights i
        LEFT JOIN insight_actions ia ON ia.insight_id = i.id
        WHERE i.target_company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
          AND i.priority IN ('critica', 'alta')
        ORDER BY
            CASE i.priority WHEN 'critica' THEN 0 ELSE 1 END,
            i.roi_score DESC
        LIMIT 8
    """)).fetchall()

    insights_data = []
    for row in insights:
        (id_, titulo, headline, descricao, acao, prazo,
         priority, impacto, esforco, roi, tipo, status) = row
        insights_data.append({
            "id": id_, "titulo": titulo, "headline": headline,
            "descricao": descricao, "acao": acao, "prazo": prazo,
            "priority": priority, "tipo": tipo,
            "impacto": impacto, "esforco": esforco,
            "roi": float(roi) if roi else 0,
            "status": status,
        })

    # Janelas de captação
    windows = db.execute(text("""
        SELECT i.id, i.titulo, i.headline, i.descricao,
               i.acao_prazo, i.priority,
               co.name as compared_name
        FROM insights i
        LEFT JOIN companies co ON co.id = i.compared_company_id
        WHERE i.target_company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
          AND i.insight_type = 'oportunidade_captacao'
        ORDER BY
            CASE i.priority WHEN 'critica' THEN 0 WHEN 'alta' THEN 1 ELSE 2 END,
            i.roi_score DESC
        LIMIT 5
    """)).fetchall()

    windows_data = [{
        "titulo": w[1], "headline": w[2], "descricao": w[3],
        "prazo": w[4], "priority": w[5], "target": w[6] or "—",
    } for w in windows]

    # Ações em andamento
    actions_in_progress = db.execute(text("""
        SELECT i.titulo, ia.notas, ia.updated_at
        FROM insight_actions ia
        JOIN insights i ON i.id = ia.insight_id
        WHERE ia.status = 'em_andamento'
        ORDER BY ia.updated_at DESC LIMIT 5
    """)).fetchall()

    return {
        "generated_at": datetime.now(),
        "c6": c6,
        "c6_rank": c6_rank,
        "total_companies": len(company_data),
        "total_reviews": sum(c["total_reviews"] for c in company_data),
        "companies": ranked,
        "dimensions": dimensions,
        "insights": insights_data,
        "windows": windows_data,
        "actions_in_progress": [
            {"titulo": a[0], "notas": a[1], "updated_at": a[2]}
            for a in actions_in_progress
        ],
    }


def generate_executive_pdf(db: Session) -> bytes:
    """Gera o PDF executivo e retorna os bytes."""
    data = _gather_report_data(db)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))

    # Filtros úteis no Jinja
    def fmt_pct(v):
        return f"{v:.0f}%" if v is not None else "—"
    def fmt_score(v):
        return f"{v:.1f}" if v is not None else "—"
    def score_class(v):
        if v >= 7: return "score-good"
        if v >= 5: return "score-ok"
        if v >= 3: return "score-warn"
        return "score-bad"
    def ordinal(n):
        return f"{n}º"
    def fmt_date(d):
        if not d: return "—"
        if isinstance(d, str): return d[:10]
        return d.strftime("%d/%m/%Y")

    env.filters["fmt_pct"]    = fmt_pct
    env.filters["fmt_score"]  = fmt_score
    env.filters["score_class"] = score_class
    env.filters["ordinal"]    = ordinal
    env.filters["fmt_date"]   = fmt_date

    template = env.get_template("executive_report.html")
    html_str = template.render(**data)

    # Renderiza com xhtml2pdf (puro Python, funciona no Windows sem GTK)
    output = io.BytesIO()
    result = pisa.CreatePDF(html_str, dest=output, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"Erro ao gerar PDF: {result.err}")
    return output.getvalue()