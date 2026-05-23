from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
import json

router = APIRouter(tags=["reviews"])


def safe_loads(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []


@router.get("/reviews")
def list_reviews(
    empresa: str = Query(
        None,
        description="Slug da empresa: c6_bank | nubank | itau_unibanco | bradesco | banco_bv | ifood | mercado_livre"
    ),
    sentimento: str = Query(None, description="positivo | negativo | misto | neutro"),
    dimensao:   str = Query(None, description="slug da dimensão ex: lideranca"),
    area:       str = Query(None, description="engenharia | produto | atendimento..."),
    nivel:      str = Query(None, description="junior | pleno | senior | lideranca..."),
    nota_min:   float = Query(None, ge=1, le=5),
    nota_max:   float = Query(None, ge=1, le=5),
    ano:        int   = Query(None, description="ex: 2024"),
    busca:      str   = Query(None, description="texto livre nos pros/contras/titulo"),
    page:       int   = Query(1, ge=1),
    page_size:  int   = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Lista reviews com filtros e paginação.
    Suporta todas as empresas analisadas (não só C6 e Nubank).
    """
    where  = ["r.is_event_review = false", "r.analysis_version IS NOT NULL"]
    params: dict = {}

    if empresa:
        where.append("c.slug = :empresa")
        params["empresa"] = empresa

    if sentimento:
        where.append("r.sentimento_geral = :sentimento")
        params["sentimento"] = sentimento

    if area:
        where.append("r.area_funcional = :area")
        params["area"] = area

    if nivel:
        where.append("r.nivel_senioridade = :nivel")
        params["nivel"] = nivel

    if nota_min is not None:
        where.append("r.avaliacao_geral >= :nota_min")
        params["nota_min"] = nota_min

    if nota_max is not None:
        where.append("r.avaliacao_geral <= :nota_max")
        params["nota_max"] = nota_max

    if ano:
        where.append("EXTRACT(YEAR FROM r.data_review) = :ano")
        params["ano"] = ano

    if busca:
        where.append(
            "(r.pros ILIKE :busca OR r.contras ILIKE :busca OR r.titulo_review ILIKE :busca)"
        )
        params["busca"] = f"%{busca}%"

    if dimensao:
        where.append("""
            EXISTS (
                SELECT 1 FROM review_dimensions rd
                JOIN dimensions d ON d.id = rd.dimension_id
                WHERE rd.review_id = r.id
                  AND d.slug = :dimensao
                  AND rd.sentiment = 'negativo'
            )
        """)
        params["dimensao"] = dimensao

    where_sql = "WHERE " + " AND ".join(where)
    offset    = (page - 1) * page_size
    params["limit"]  = page_size
    params["offset"] = offset

    # Total
    total = db.execute(text(f"""
        SELECT COUNT(*)
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        {where_sql}
    """), params).scalar()

    # Reviews
    rows = db.execute(text(f"""
        SELECT r.id, c.name AS empresa, c.slug AS empresa_slug,
               r.cargo, r.localizacao, r.data_review,
               r.status_funcionario, r.tempo_empresa,
               r.avaliacao_geral, r.recomendaria, r.aprovacao_ceo,
               r.titulo_review, r.pros, r.contras, r.conselho_presidencia,
               r.sentimento_geral, r.intensidade_emocional,
               r.nivel_senioridade, r.area_funcional,
               r.momento_experiencia, r.resumo_ia,
               r.temas_emergentes, r.menciona_concorrentes,
               r.tem_linguagem_saudosismo, r.tem_linguagem_revolta,
               r.tem_linguagem_admiracao, r.quality_score
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        {where_sql}
        ORDER BY r.intensidade_emocional DESC NULLS LAST, r.data_review DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    reviews = []
    for row in rows:
        (id_, empresa_name, empresa_slug, cargo, loc, data_r,
         status, tempo, nota, rec, ceo,
         titulo, pros, contras, conselho,
         sentimento, intensidade, nivel, area, momento, resumo,
         temas, concorrentes, saudosismo, revolta, admiracao, quality) = row

        reviews.append({
            "id":                  id_,
            "empresa":             empresa_name,
            "empresa_slug":        empresa_slug,
            "cargo":               cargo,
            "localizacao":         loc,
            "data_review":         str(data_r) if data_r else None,
            "status_funcionario":  status,
            "tempo_empresa":       tempo,
            "avaliacao_geral":     nota,
            "recomendaria":        rec,
            "aprovacao_ceo":       ceo,
            "titulo_review":       titulo,
            "pros":                pros,
            "contras":             contras,
            "conselho_presidencia": conselho,
            "sentimento_geral":    sentimento,
            "intensidade_emocional": intensidade,
            "nivel_senioridade":   nivel,
            "area_funcional":      area,
            "momento_experiencia": momento,
            "resumo_ia":           resumo,
            "temas_emergentes":    safe_loads(temas),
            "menciona_concorrentes": safe_loads(concorrentes),
            "linguagem": {
                "saudosismo": bool(saudosismo),
                "revolta":    bool(revolta),
                "admiracao":  bool(admiracao),
            },
            "quality_score": float(quality) if quality else None,
        })

    return {
        "reviews":   reviews,
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     -(-total // page_size),  # ceil division
    }


@router.get("/reviews/stats/empresas")
def reviews_stats_empresas(db: Session = Depends(get_db)):
    """
    Retorna lista de todas as empresas disponíveis com contagem de reviews.
    Útil para popular filtros no frontend.
    """
    rows = db.execute(text("""
        SELECT c.slug, c.name, c.is_target,
               COUNT(r.id) AS total,
               ROUND(AVG(r.avaliacao_geral)::numeric, 2) AS avg_nota,
               SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) AS pos,
               SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) AS neg
        FROM companies c
        LEFT JOIN reviews r ON r.company_id = c.id
            AND r.is_event_review = false AND r.analysis_version IS NOT NULL
        WHERE c.is_active = true
        GROUP BY c.slug, c.name, c.is_target
        ORDER BY c.is_target DESC, COUNT(r.id) DESC
    """)).fetchall()

    empresas = []
    for slug, name, is_target, total, avg_nota, pos, neg in rows:
        total = total or 0
        mix   = total - (pos or 0) - (neg or 0)
        score = round(((pos or 0) * 1.0 + mix * 0.5) / total * 10, 1) if total else 0
        empresas.append({
            "slug":            slug,
            "name":            name,
            "is_target":       is_target,
            "total_reviews":   total,
            "avg_nota":        float(avg_nota) if avg_nota else 0,
            "sentiment_score": score,
            "pct_positivo":    round((pos or 0) / total * 100, 1) if total else 0,
            "pct_negativo":    round((neg or 0) / total * 100, 1) if total else 0,
        })

    return {"empresas": empresas, "total_empresas": len(empresas)}


@router.get("/reviews/{review_id}")
def get_review(review_id: int, db: Session = Depends(get_db)):
    """Detalhes de uma review específica com suas dimensões analisadas."""

    row = db.execute(text("""
        SELECT r.id, c.name AS empresa, c.slug AS empresa_slug,
               r.cargo, r.localizacao, r.data_review,
               r.status_funcionario, r.tempo_empresa,
               r.avaliacao_geral, r.recomendaria, r.aprovacao_ceo,
               r.titulo_review, r.pros, r.contras, r.conselho_presidencia,
               r.sentimento_geral, r.intensidade_emocional,
               r.nivel_senioridade, r.area_funcional,
               r.momento_experiencia, r.resumo_ia,
               r.temas_emergentes, r.menciona_concorrentes,
               r.tem_linguagem_saudosismo, r.tem_linguagem_revolta,
               r.tem_linguagem_admiracao, r.quality_score
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.id = :id
    """), {"id": review_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Review não encontrada")

    (id_, empresa_name, empresa_slug, cargo, loc, data_r,
     status, tempo, nota, rec, ceo,
     titulo, pros, contras, conselho,
     sentimento, intensidade, nivel, area, momento, resumo,
     temas, concorrentes, saudosismo, revolta, admiracao, quality) = row

    # Dimensões analisadas pela IA
    dims = db.execute(text("""
        SELECT d.name, d.slug, rd.sentiment, rd.intensity,
               rd.evidence_quote, rd.is_primary, rd.confidence
        FROM review_dimensions rd
        JOIN dimensions d ON d.id = rd.dimension_id
        WHERE rd.review_id = :id AND rd.analysis_version = 'v1'
        ORDER BY rd.is_primary DESC, rd.intensity DESC
    """), {"id": review_id}).fetchall()

    dimensoes = [
        {
            "dimensao":       d[0],
            "slug":           d[1],
            "sentiment":      d[2],
            "intensity":      d[3],
            "evidence_quote": d[4],
            "is_primary":     d[5],
            "confidence":     float(d[6]) if d[6] else None,
        }
        for d in dims
    ]

    return {
        "id":                  id_,
        "empresa":             empresa_name,
        "empresa_slug":        empresa_slug,
        "cargo":               cargo,
        "localizacao":         loc,
        "data_review":         str(data_r) if data_r else None,
        "status_funcionario":  status,
        "tempo_empresa":       tempo,
        "avaliacao_geral":     nota,
        "recomendaria":        rec,
        "aprovacao_ceo":       ceo,
        "titulo_review":       titulo,
        "pros":                pros,
        "contras":             contras,
        "conselho_presidencia": conselho,
        "sentimento_geral":    sentimento,
        "intensidade_emocional": intensidade,
        "nivel_senioridade":   nivel,
        "area_funcional":      area,
        "momento_experiencia": momento,
        "resumo_ia":           resumo,
        "temas_emergentes":    safe_loads(temas),
        "menciona_concorrentes": safe_loads(concorrentes),
        "linguagem": {
            "saudosismo": bool(saudosismo),
            "revolta":    bool(revolta),
            "admiracao":  bool(admiracao),
        },
        "quality_score": float(quality) if quality else None,
        "dimensoes":     dimensoes,
    }


@router.get("/reviews/stats/by-dimension")
def reviews_by_dimension(
    empresa: str = Query("c6_bank", description="Slug da empresa"),
    db: Session = Depends(get_db),
):
    """
    Distribuição de sentimento por dimensão para qualquer empresa.
    Útil para gráficos de detalhamento no frontend.
    """
    rows = db.execute(text("""
        SELECT d.name, d.slug,
               rd.sentiment,
               COUNT(*) AS total,
               AVG(rd.intensity) AS avg_intensity
        FROM review_dimensions rd
        JOIN dimensions d ON d.id = rd.dimension_id
        JOIN reviews r ON r.id = rd.review_id
        JOIN companies c ON c.id = r.company_id
        WHERE c.slug = :empresa
          AND rd.analysis_version = 'v1'
          AND r.is_event_review = false
        GROUP BY d.name, d.slug, d.display_order, rd.sentiment
        ORDER BY d.display_order, rd.sentiment
    """), {"empresa": empresa}).fetchall()

    by_dim: dict = {}
    for name, slug, sentiment, total, avg_int in rows:
        if slug not in by_dim:
            by_dim[slug] = {
                "name": name, "slug": slug,
                "positivo": 0, "negativo": 0, "misto": 0, "neutro": 0,
                "avg_intensity": 0,
            }
        by_dim[slug][sentiment] = total
        if sentiment == "negativo":
            by_dim[slug]["avg_intensity"] = round(float(avg_int), 1) if avg_int else 0

    return {"dimensions": list(by_dim.values()), "empresa": empresa}