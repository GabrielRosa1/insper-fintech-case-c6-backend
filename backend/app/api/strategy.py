"""
API de Estratégia & Ações — Onda 3

Endpoints:
- GET  /strategy/windows                — janelas de captação ativas
- GET  /strategy/actions                — status de tracking de todos os insights
- PATCH /strategy/actions/{insight_id}  — atualiza status/notas
- POST /strategy/playbook               — gera playbook on-demand via Claude Haiku
- GET  /strategy/playbook/{insight_id}  — recupera playbook em cache
- GET  /strategy/report/pdf             — gera PDF executivo
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import json
import time
import io

from app.database import get_db
from app.config import get_settings
import anthropic

settings = get_settings()
client   = anthropic.Anthropic(api_key=settings.anthropic_api_key)

router = APIRouter(tags=["strategy"])

PLAYBOOK_MODEL    = "claude-haiku-4-5-20251001"
PLAYBOOK_TTL_HRS  = 24


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def safe_loads(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []


# ══════════════════════════════════════════════════════════════════════════════
# JANELAS DE CAPTAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/strategy/windows")
def get_captation_windows(db: Session = Depends(get_db)):
    """
    Retorna janelas de captação ativas — insights tipo 'oportunidade_captacao'
    enriquecidos com dados das empresas referenciadas.
    """
    # Pega insights que são oportunidades de captação
    rows = db.execute(text("""
        SELECT i.id, i.titulo, i.headline, i.descricao,
               i.acao_recomendada, i.acao_prazo, i.acao_responsavel,
               i.priority, i.impacto_score, i.esforco_score, i.roi_score,
               i.supporting_quotes, i.is_featured,
               co.slug as compared_slug, co.name as compared_name,
               ia.status, ia.notas, ia.updated_at as action_updated
        FROM insights i
        LEFT JOIN companies co ON co.id = i.compared_company_id
        LEFT JOIN insight_actions ia ON ia.insight_id = i.id
        WHERE i.target_company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
          AND (i.insight_type IN ('oportunidade_captacao', 'benchmark_positivo')
               OR i.is_active_window = true)
        ORDER BY
            CASE i.priority
                WHEN 'critica' THEN 0 WHEN 'alta' THEN 1
                WHEN 'media' THEN 2 ELSE 3 END,
            i.roi_score DESC
    """)).fetchall()

    windows = []
    for row in rows:
        (id_, titulo, headline, descricao, acao, prazo, responsavel,
         priority, impacto, esforco, roi, quotes_raw, featured,
         compared_slug, compared_name, status, notas, action_updated) = row

        quotes = safe_loads(quotes_raw)

        # Para cada janela, busca dados ricos da empresa-alvo se houver
        target_data = None
        if compared_slug:
            target_data = _get_target_company_snapshot(db, compared_slug)

        windows.append({
            "id":               id_,
            "titulo":           titulo,
            "headline":         headline,
            "descricao":        descricao,
            "acao_recomendada": acao,
            "acao_prazo":       prazo,
            "acao_responsavel": responsavel,
            "priority":         priority,
            "impacto_score":    impacto,
            "esforco_score":    esforco,
            "roi_score":        float(roi) if roi else 0,
            "supporting_quotes": quotes[:3],
            "is_featured":      featured,
            "target": {
                "slug": compared_slug,
                "name": compared_name,
                "snapshot": target_data,
            } if compared_slug else None,
            "action": {
                "status": status or "pendente",
                "notas":  notas,
                "updated_at": str(action_updated) if action_updated else None,
            },
        })

    # Categoriza
    critical_windows = [w for w in windows if w["priority"] == "critica"]
    high_windows     = [w for w in windows if w["priority"] == "alta"]
    other_windows    = [w for w in windows if w["priority"] not in ("critica", "alta")]

    return {
        "windows":   windows,
        "critical":  critical_windows,
        "high":      high_windows,
        "other":     other_windows,
        "total":     len(windows),
    }


def _get_target_company_snapshot(db: Session, slug: str) -> dict | None:
    """Retorna snapshot rápido de uma empresa-alvo para enriquecer janelas."""
    row = db.execute(text("""
        SELECT c.name,
               COUNT(r.id) as total,
               ROUND(AVG(r.avaliacao_geral)::numeric, 2) as avg_nota,
               SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) as pos,
               SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) as neg
        FROM companies c
        LEFT JOIN reviews r ON r.company_id = c.id
            AND r.is_event_review = false AND r.analysis_version IS NOT NULL
        WHERE c.slug = :slug
        GROUP BY c.name
    """), {"slug": slug}).fetchone()

    if not row or not row[1]:
        return None

    name, total, avg_nota, pos, neg = row

    # Worst dimensions (oportunidade de captação = onde o alvo é fraco)
    worst_dims = db.execute(text("""
        SELECT d.name, s.sentiment_score
        FROM company_dimension_stats s
        JOIN dimensions d ON d.id = s.dimension_id
        WHERE s.company_id = (SELECT id FROM companies WHERE slug = :slug)
          AND s.period = 'all' AND s.analysis_version = 'v1'
          AND s.total_mentions >= 5
        ORDER BY s.sentiment_score ASC
        LIMIT 3
    """), {"slug": slug}).fetchall()

    return {
        "total_reviews": total or 0,
        "avg_nota":      float(avg_nota) if avg_nota else 0,
        "pct_negativo":  round((neg or 0) / total * 100, 1) if total else 0,
        "weak_dimensions": [
            {"name": d[0], "score": float(d[1]) if d[1] else 0}
            for d in worst_dims
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# AÇÕES (TRACKING)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/strategy/actions")
def list_actions(
    status: str | None = Query(None, description="pendente | em_andamento | concluida | descartada"),
    db: Session = Depends(get_db),
):
    """Lista status de tracking de cada insight do C6 Bank."""
    where = ["i.target_company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')"]
    params: dict = {}

    if status:
        where.append("COALESCE(ia.status, 'pendente') = :status")
        params["status"] = status

    rows = db.execute(text(f"""
        SELECT i.id, i.titulo, i.headline, i.insight_type, i.priority,
               i.impacto_score, i.esforco_score, i.roi_score, i.acao_prazo,
               COALESCE(ia.status, 'pendente') as status,
               ia.notas, ia.updated_at, ia.atualizado_por
        FROM insights i
        LEFT JOIN insight_actions ia ON ia.insight_id = i.id
        WHERE {' AND '.join(where)}
        ORDER BY
            CASE COALESCE(ia.status, 'pendente')
                WHEN 'em_andamento' THEN 0
                WHEN 'pendente' THEN 1
                WHEN 'concluida' THEN 2
                ELSE 3 END,
            CASE i.priority
                WHEN 'critica' THEN 0 WHEN 'alta' THEN 1
                WHEN 'media' THEN 2 ELSE 3 END,
            i.roi_score DESC
    """), params).fetchall()

    actions = []
    summary: dict = {"pendente": 0, "em_andamento": 0, "concluida": 0, "descartada": 0}

    for row in rows:
        (id_, titulo, headline, tipo, priority,
         impacto, esforco, roi, prazo,
         status_, notas, updated, atualizado_por) = row

        summary[status_] = summary.get(status_, 0) + 1

        actions.append({
            "insight_id":     id_,
            "titulo":         titulo,
            "headline":       headline,
            "tipo":           tipo,
            "priority":       priority,
            "impacto_score":  impacto,
            "esforco_score":  esforco,
            "roi_score":      float(roi) if roi else 0,
            "acao_prazo":     prazo,
            "status":         status_,
            "notas":          notas,
            "updated_at":     str(updated) if updated else None,
            "atualizado_por": atualizado_por,
        })

    return {"actions": actions, "summary": summary, "total": len(actions)}


class UpdateActionRequest(BaseModel):
    status: str | None = None
    notas:  str | None = None
    atualizado_por: str | None = None


@router.patch("/strategy/actions/{insight_id}")
def update_action(
    insight_id: int,
    req: UpdateActionRequest,
    db: Session = Depends(get_db),
):
    """Atualiza status e/ou notas de um insight."""

    # Valida status
    if req.status and req.status not in ("pendente", "em_andamento", "concluida", "descartada"):
        raise HTTPException(400, f"Status inválido: {req.status}")

    # Verifica se o insight existe
    insight_row = db.execute(
        text("SELECT id FROM insights WHERE id = :id"), {"id": insight_id}
    ).fetchone()
    if not insight_row:
        raise HTTPException(404, "Insight não encontrado.")

    # UPSERT
    existing = db.execute(
        text("SELECT id FROM insight_actions WHERE insight_id = :iid"),
        {"iid": insight_id}
    ).fetchone()

    if existing:
        # UPDATE
        set_parts = []
        params = {"iid": insight_id, "now": datetime.now(timezone.utc)}
        if req.status is not None:
            set_parts.append("status = :status")
            params["status"] = req.status
        if req.notas is not None:
            set_parts.append("notas = :notas")
            params["notas"] = req.notas
        if req.atualizado_por is not None:
            set_parts.append("atualizado_por = :atualizado_por")
            params["atualizado_por"] = req.atualizado_por
        set_parts.append("updated_at = :now")

        db.execute(text(f"""
            UPDATE insight_actions SET {', '.join(set_parts)}
            WHERE insight_id = :iid
        """), params)
    else:
        # INSERT
        db.execute(text("""
            INSERT INTO insight_actions (insight_id, status, notas, atualizado_por)
            VALUES (:iid, :status, :notas, :atualizado_por)
        """), {
            "iid": insight_id,
            "status": req.status or "pendente",
            "notas": req.notas,
            "atualizado_por": req.atualizado_por,
        })

    db.commit()

    # Retorna estado atual
    row = db.execute(text("""
        SELECT status, notas, atualizado_por, updated_at
        FROM insight_actions WHERE insight_id = :iid
    """), {"iid": insight_id}).fetchone()

    return {
        "insight_id":     insight_id,
        "status":         row[0],
        "notas":          row[1],
        "atualizado_por": row[2],
        "updated_at":     str(row[3]) if row[3] else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PLAYBOOKS (GERAÇÃO ON-DEMAND VIA CLAUDE HAIKU)
# ══════════════════════════════════════════════════════════════════════════════

PLAYBOOK_SYSTEM = """Você é um consultor sênior de captação de talentos para o C6 Bank.

Sua tarefa é, a partir de um insight estratégico, gerar um playbook acionável e específico
para captar talentos de um concorrente. O playbook deve ser direto, com argumentos baseados
em dados, e produzir uma mensagem de outreach que um recrutador pode usar imediatamente.

Responda SEMPRE em JSON válido, sem markdown, sem backticks, sem texto antes ou depois."""


PLAYBOOK_USER_TEMPLATE = """Gere um playbook de captação a partir deste insight:

## Insight
- Título: {titulo}
- Headline: {headline}
- Descrição: {descricao}
- Ação recomendada: {acao_recomendada}

## Empresa-alvo (de onde vamos captar)
{target_context}

## Vantagens do C6 Bank vs essa empresa
{c6_vantagens}

## Vagas atuais do C6 que podem se beneficiar
{vagas_c6}

Retorne um JSON com esta estrutura EXATA:

{{
  "persona_titulo": "Título curto da persona-alvo (max 80 chars)",
  "persona_descricao": "Descrição em 1-2 frases do perfil de talento que estamos captando",
  "argumentos_ancora": [
    {{"argumento": "...", "evidencia_dados": "score X.X/10 em ..., baseado em N reviews"}},
    {{"argumento": "...", "evidencia_dados": "..."}}
  ],
  "pontos_de_cuidado": [
    {{"ponto": "Algo que o C6 também precisa melhorar ou que pode ser questionado",
      "como_endereçar": "Como reconhecer honestamente sem afastar o candidato"}}
  ],
  "quotes_recomendadas": [
    {{"empresa_origem": "C6 Bank | <concorrente>", "quote": "trecho literal", "uso": "como usar em conversa"}}
  ],
  "dimensoes_destaque": ["nome dimensão 1", "nome dimensão 2"],
  "mensagem_linkedin": "Mensagem completa pronta para enviar via LinkedIn (3-5 parágrafos, tom profissional mas humano, sem clichês de recrutador)",
  "email_sugerido": "Versão mais formal em formato de e-mail (4-6 parágrafos)",
  "canais_recomendados": ["LinkedIn DM", "Email", "Comunidade X", "Evento Y"]
}}

REGRAS:
- Os argumentos devem citar dados REAIS dos scores fornecidos
- A mensagem do LinkedIn precisa começar com algo personalizado (não 'Olá, vi seu perfil...')
- Inclua um call-to-action claro no fim das mensagens
- Honestidade > marketing — se o C6 também tem problema na dimensão, mencione brevemente
- Tom: consultor sênior conversando com par sênior, não recrutador agressivo"""


class GeneratePlaybookRequest(BaseModel):
    insight_id: int
    force_regenerate: bool = False


@router.post("/strategy/playbook")
def generate_playbook(req: GeneratePlaybookRequest, db: Session = Depends(get_db)):
    """Gera playbook on-demand a partir de um insight, com cache de 24h."""

    # Verifica cache
    if not req.force_regenerate:
        cached = db.execute(text("""
            SELECT id, persona_titulo, persona_descricao, argumentos_ancora,
                   pontos_de_cuidado, quotes_recomendadas, dimensoes_destaque,
                   mensagem_linkedin, email_sugerido, canais_recomendados,
                   model_used, created_at, expires_at, target_company_slug
            FROM captation_playbooks
            WHERE insight_id = :iid AND expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT 1
        """), {"iid": req.insight_id}).fetchone()

        if cached:
            return _serialize_playbook(cached, from_cache=True)

    # Busca dados do insight
    insight = db.execute(text("""
        SELECT i.titulo, i.headline, i.descricao, i.acao_recomendada,
               co.slug as compared_slug, co.name as compared_name
        FROM insights i
        LEFT JOIN companies co ON co.id = i.compared_company_id
        WHERE i.id = :iid
    """), {"iid": req.insight_id}).fetchone()

    if not insight:
        raise HTTPException(404, "Insight não encontrado.")

    titulo, headline, descricao, acao, compared_slug, compared_name = insight

    # Monta contexto da empresa-alvo
    if compared_slug:
        target_context = _build_target_context(db, compared_slug, compared_name)
    else:
        target_context = "Não há empresa específica vinculada — gere playbook genérico para mercado."
        compared_slug = "mercado"

    # Monta vantagens C6
    c6_vantagens = _build_c6_advantages(db, compared_slug if compared_slug != "mercado" else None)

    # Vagas C6 relevantes
    vagas_c6 = _build_vagas_c6(db)

    # Chama Claude Haiku
    prompt = PLAYBOOK_USER_TEMPLATE.format(
        titulo=titulo,
        headline=headline or "",
        descricao=descricao or "",
        acao_recomendada=acao or "",
        target_context=target_context,
        c6_vantagens=c6_vantagens,
        vagas_c6=vagas_c6,
    )

    start = time.time()
    response = client.messages.create(
        model=PLAYBOOK_MODEL,
        max_tokens=3000,
        system=PLAYBOOK_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = int((time.time() - start) * 1000)

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"Falha ao parsear playbook gerado: {e}")

    tokens = response.usage.input_tokens + response.usage.output_tokens
    # Haiku 4.5: $1/M input, $5/M output (aproximação)
    cost = (response.usage.input_tokens / 1_000_000 * 1.0) + (response.usage.output_tokens / 1_000_000 * 5.0)

    # Persiste no cache
    expires_at = datetime.now(timezone.utc) + timedelta(hours=PLAYBOOK_TTL_HRS)

    inserted = db.execute(text("""
        INSERT INTO captation_playbooks (
            insight_id, target_company_slug,
            persona_titulo, persona_descricao,
            argumentos_ancora, pontos_de_cuidado,
            quotes_recomendadas, dimensoes_destaque,
            mensagem_linkedin, email_sugerido, canais_recomendados,
            model_used, tokens_used, generation_cost, expires_at
        ) VALUES (
            :iid, :tslug,
            :ptitle, :pdesc,
            :args, :cuidados,
            :quotes, :dims,
            :linkedin, :email, :canais,
            :model, :tokens, :cost, :expires
        ) RETURNING id, created_at
    """), {
        "iid":     req.insight_id,
        "tslug":   compared_slug,
        "ptitle":  result.get("persona_titulo", ""),
        "pdesc":   result.get("persona_descricao", ""),
        "args":    json.dumps(result.get("argumentos_ancora", []), ensure_ascii=False),
        "cuidados": json.dumps(result.get("pontos_de_cuidado", []), ensure_ascii=False),
        "quotes":  json.dumps(result.get("quotes_recomendadas", []), ensure_ascii=False),
        "dims":    json.dumps(result.get("dimensoes_destaque", []), ensure_ascii=False),
        "linkedin": result.get("mensagem_linkedin", ""),
        "email":   result.get("email_sugerido", ""),
        "canais":  json.dumps(result.get("canais_recomendados", []), ensure_ascii=False),
        "model":   PLAYBOOK_MODEL,
        "tokens":  tokens,
        "cost":    cost,
        "expires": expires_at,
    }).fetchone()

    db.commit()

    return {
        "id":               inserted[0],
        "insight_id":       req.insight_id,
        "target_slug":      compared_slug,
        "from_cache":       False,
        "persona_titulo":   result.get("persona_titulo"),
        "persona_descricao": result.get("persona_descricao"),
        "argumentos_ancora": result.get("argumentos_ancora", []),
        "pontos_de_cuidado": result.get("pontos_de_cuidado", []),
        "quotes_recomendadas": result.get("quotes_recomendadas", []),
        "dimensoes_destaque": result.get("dimensoes_destaque", []),
        "mensagem_linkedin": result.get("mensagem_linkedin", ""),
        "email_sugerido":   result.get("email_sugerido", ""),
        "canais_recomendados": result.get("canais_recomendados", []),
        "model_used":       PLAYBOOK_MODEL,
        "tokens_used":      tokens,
        "generation_cost":  round(cost, 5),
        "latency_ms":       latency_ms,
        "created_at":       str(inserted[1]),
        "expires_at":       str(expires_at),
    }


@router.get("/strategy/playbook/{insight_id}")
def get_playbook(insight_id: int, db: Session = Depends(get_db)):
    """Recupera o último playbook em cache para o insight."""
    row = db.execute(text("""
        SELECT id, persona_titulo, persona_descricao, argumentos_ancora,
               pontos_de_cuidado, quotes_recomendadas, dimensoes_destaque,
               mensagem_linkedin, email_sugerido, canais_recomendados,
               model_used, created_at, expires_at, target_company_slug
        FROM captation_playbooks
        WHERE insight_id = :iid
        ORDER BY created_at DESC LIMIT 1
    """), {"iid": insight_id}).fetchone()

    if not row:
        raise HTTPException(404, "Nenhum playbook gerado ainda para este insight.")

    return _serialize_playbook(row, from_cache=True)


def _serialize_playbook(row, from_cache: bool = False) -> dict:
    (id_, ptitle, pdesc, args, cuidados, quotes, dims,
     linkedin, email, canais, model, created, expires, target_slug) = row

    return {
        "id":                id_,
        "from_cache":        from_cache,
        "target_slug":       target_slug,
        "persona_titulo":    ptitle,
        "persona_descricao": pdesc,
        "argumentos_ancora": safe_loads(args),
        "pontos_de_cuidado": safe_loads(cuidados),
        "quotes_recomendadas": safe_loads(quotes),
        "dimensoes_destaque": safe_loads(dims),
        "mensagem_linkedin": linkedin,
        "email_sugerido":    email,
        "canais_recomendados": safe_loads(canais),
        "model_used":        model,
        "created_at":        str(created) if created else None,
        "expires_at":        str(expires) if expires else None,
        "is_expired":        expires and expires < datetime.now(timezone.utc) if expires else False,
    }


# Helpers de contexto para playbook
def _build_target_context(db: Session, slug: str, name: str) -> str:
    """Monta contexto rico sobre a empresa-alvo para o prompt."""
    snapshot = _get_target_company_snapshot(db, slug)
    if not snapshot:
        return f"{name}: dados não disponíveis"

    weak_str = "\n".join([
        f"  - {d['name']}: {d['score']:.1f}/10 (PROBLEMA EXPLORÁVEL)"
        for d in snapshot["weak_dimensions"]
    ])

    return f"""{name}:
- Total reviews analisadas: {snapshot['total_reviews']}
- Nota média Glassdoor: {snapshot['avg_nota']:.1f}/5
- % sentimento negativo: {snapshot['pct_negativo']:.0f}%

Dimensões mais fracas (oportunidades de captação):
{weak_str}"""


def _build_c6_advantages(db: Session, compared_slug: str | None) -> str:
    """Monta lista de dimensões onde o C6 ganha (ou está empatado)."""
    if compared_slug:
        rows = db.execute(text("""
            SELECT d.name,
                   s1.sentiment_score as c6_score,
                   s2.sentiment_score as comp_score
            FROM dimensions d
            LEFT JOIN company_dimension_stats s1
                ON s1.dimension_id = d.id AND s1.period = 'all'
                AND s1.analysis_version = 'v1'
                AND s1.company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
            LEFT JOIN company_dimension_stats s2
                ON s2.dimension_id = d.id AND s2.period = 'all'
                AND s2.analysis_version = 'v1'
                AND s2.company_id = (SELECT id FROM companies WHERE slug = :slug)
            WHERE d.is_active = true
              AND s1.sentiment_score IS NOT NULL
              AND s2.sentiment_score IS NOT NULL
            ORDER BY (s1.sentiment_score - s2.sentiment_score) DESC
            LIMIT 5
        """), {"slug": compared_slug}).fetchall()

        lines = []
        for name, c6_s, comp_s in rows:
            diff = float(c6_s) - float(comp_s)
            if diff > 0.5:
                lines.append(f"  - {name}: C6 {float(c6_s):.1f} vs {compared_slug} {float(comp_s):.1f} (vantagem +{diff:.1f})")
            elif diff > -0.5:
                lines.append(f"  - {name}: C6 {float(c6_s):.1f} vs {compared_slug} {float(comp_s):.1f} (empate)")
        return "\n".join(lines) if lines else "Sem vantagens claras detectadas — playbook deve focar em outras alavancas."
    else:
        # Top 5 dims do C6
        rows = db.execute(text("""
            SELECT d.name, s.sentiment_score
            FROM company_dimension_stats s
            JOIN dimensions d ON d.id = s.dimension_id
            WHERE s.company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
              AND s.period = 'all' AND s.analysis_version = 'v1'
            ORDER BY s.sentiment_score DESC
            LIMIT 5
        """)).fetchall()
        return "\n".join([f"  - {r[0]}: score {float(r[1]):.1f}/10" for r in rows])


def _build_vagas_c6(db: Session) -> str:
    """Top 5 áreas com vagas abertas no C6."""
    rows = db.execute(text("""
        SELECT area, COUNT(*) as cnt
        FROM jobs
        WHERE company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
        GROUP BY area ORDER BY cnt DESC LIMIT 5
    """)).fetchall()
    return "\n".join([f"  - {r[0]}: {r[1]} vagas abertas" for r in rows]) or "Sem dados de vagas."


# ══════════════════════════════════════════════════════════════════════════════
# RELATÓRIO EXECUTIVO (PDF)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/strategy/report/pdf")
def get_executive_report(db: Session = Depends(get_db)):
    """Gera um PDF executivo do estado do employer branding."""
    from app.services.pdf_report import generate_executive_pdf

    pdf_bytes = generate_executive_pdf(db)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=c6-employer-branding-executive-{datetime.now().strftime('%Y%m%d')}.pdf"
        },
    )