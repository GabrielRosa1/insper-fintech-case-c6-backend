from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from pydantic import BaseModel
import anthropic
import voyageai
import os
import json
import uuid
import time
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(tags=["chat"])

anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
voyage_client    = voyageai.Client(
    api_key=os.environ.get("VOYAGE_API_KEY", os.environ["ANTHROPIC_API_KEY"])
)

EMBEDDING_MODEL = "voyage-3"
CHAT_MODEL      = "claude-haiku-4-5-20251001"
RAG_LIMIT       = 12
MAX_HISTORY     = 10

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Você é um consultor sênior especializado em Employer Branding e estratégia de talentos, \
contratado exclusivamente pelo **C6 Bank** para apoiar decisões de captação e retenção.

## Contexto do projeto
Você tem acesso a uma base de dados proprietária com reviews reais de funcionários de **{total_companies} empresas** \
analisadas via Claude IA (Glassdoor) e vagas do LinkedIn:

{companies_context}

Total: **{total_reviews} reviews** + **{total_jobs} vagas** analisadas · 9 dimensões de employer branding

## Scorecard de mercado — score 0–10 (maior = melhor percepção)
{scorecard_table}

## Ranking geral por sentimento (1º = melhor empregador percebido)
{ranking_context}

## Eventos recentes relevantes
{events_context}

## Sua missão
Apoiar o C6 Bank em:
1. **Captar talentos** identificando janelas de oportunidade em cada concorrente
2. **Reter funcionários** com base nos drivers reais de saída
3. **Fechar gaps** entre o que as vagas prometem e o que os funcionários vivem
4. **Comunicar vantagens reais** do C6 que estão sendo subutilizadas

## Como responder
- Use os dados de TODAS as empresas disponíveis — compare amplamente quando relevante
- Ao mencionar um concorrente, cite seu score e posição no ranking para dar contexto
- Identifique quais problemas são **exclusivos do C6** vs **endêmicos do setor**
- Cite trechos literais das reviews entre aspas como evidência
- Seja direto e estratégico — fale como consultor sênior
- Use markdown: **negrito** para pontos críticos, ## para seções, listas para ações
- Respostas entre 3–6 parágrafos, ou lista estruturada quando mais útil
- Responda SEMPRE em português brasileiro
- Se não houver evidência suficiente nas reviews fornecidas, diga claramente"""


def build_system_prompt(db: Session) -> str:
    # ── Contagem de reviews por empresa ──────────────────────────────────────
    counts = db.execute(text("""
        SELECT c.slug, c.name, COUNT(r.id) as total,
               ROUND(AVG(r.avaliacao_geral)::numeric, 2) as avg_nota,
               SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) as pos,
               SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) as neg
        FROM companies c
        LEFT JOIN reviews r ON r.company_id = c.id
            AND r.is_event_review = false AND r.analysis_version IS NOT NULL
        WHERE c.is_active = true
        GROUP BY c.slug, c.name, c.is_target
        ORDER BY c.is_target DESC, c.name
    """)).fetchall()

    total_reviews = sum(r[2] or 0 for r in counts)
    total_jobs = db.execute(text("SELECT COUNT(*) FROM jobs")).scalar() or 0

    # Calcula sentiment_score e ranking
    companies_with_score = []
    for slug, name, total, avg_nota, pos, neg in counts:
        if total:
            mix = total - (pos or 0) - (neg or 0)
            score = round(((pos or 0) * 1.0 + mix * 0.5) / total * 10, 1)
        else:
            score = 0
        companies_with_score.append((slug, name, total or 0, float(avg_nota or 0), score))

    ranked = sorted(companies_with_score, key=lambda x: -x[4])

    # Companies context
    companies_lines = []
    for rank_idx, (slug, name, total, avg_nota, score) in enumerate(ranked):
        tag = " ← TARGET" if slug == "c6_bank" else ""
        companies_lines.append(
            f"- **{name}**{tag}: {total} reviews · nota {avg_nota:.1f}/5 · sentimento {score:.1f}/10"
        )
    companies_context = "\n".join(companies_lines)

    # Ranking context
    ranking_lines = []
    for i, (slug, name, total, avg_nota, score) in enumerate(ranked):
        tag = " ← C6" if slug == "c6_bank" else ""
        ranking_lines.append(f"{i+1}º {name}{tag} — {score:.1f}/10")
    ranking_context = " | ".join(ranking_lines)

    # ── Scorecard por dimensão ────────────────────────────────────────────────
    # BUG CORRIGIDO: alias "d" agora está declarado no FROM
    dims = db.execute(text("""
        SELECT d.name, d.display_order
        FROM dimensions d
        WHERE d.is_active = true
        ORDER BY d.display_order
    """)).fetchall()

    all_scores = db.execute(text("""
        SELECT c.slug, c.name, d.name as dim_name, d.display_order,
               s.sentiment_score, s.total_mentions
        FROM company_dimension_stats s
        JOIN companies  c ON c.id = s.company_id
        JOIN dimensions d ON d.id = s.dimension_id
        WHERE s.period = 'all' AND s.analysis_version = 'v1'
          AND d.is_active = true AND c.is_active = true
        ORDER BY d.display_order, s.sentiment_score DESC
    """)).fetchall()

    # Agrupa por dimensão
    dim_scores: dict = {}
    for slug, name, dim_name, d_order, score, mentions in all_scores:
        if dim_name not in dim_scores:
            dim_scores[dim_name] = {"order": d_order, "companies": {}}
        dim_scores[dim_name]["companies"][slug] = (name, float(score) if score else 0, mentions or 0)

    # Monta tabela compacta — colunas dinâmicas a partir das empresas no banco
    company_order = ["c6_bank", "nubank", "ifood", "banco_bv", "bradesco", "itau_unibanco", "mercado_livre"]
    company_abbrev = {
        "c6_bank": "C6", "nubank": "Nu", "ifood": "iFood",
        "banco_bv": "BV", "bradesco": "Brad", "itau_unibanco": "Itaú", "mercado_livre": "ML",
    }

    header_cols = ["Dimensão"] + [company_abbrev.get(s, s) for s in company_order] + ["Líder"]
    scorecard_rows = [
        "| " + " | ".join(header_cols) + " |",
        "| " + " | ".join(["---"] * len(header_cols)) + " |",
    ]

    for dim_name, dim_data in sorted(dim_scores.items(), key=lambda x: x[1]["order"]):
        co_data = dim_data["companies"]
        cols = [dim_name]
        scores_for_dim = []
        for slug in company_order:
            if slug in co_data:
                s = co_data[slug][1]
                cols.append(f"{s:.1f}")
                scores_for_dim.append((slug, s))
            else:
                cols.append("—")
        if scores_for_dim:
            leader_slug = max(scores_for_dim, key=lambda x: x[1])
            cols.append(f"{company_abbrev.get(leader_slug[0], leader_slug[0])} ({leader_slug[1]:.1f})")
        else:
            cols.append("—")
        scorecard_rows.append("| " + " | ".join(cols) + " |")

    scorecard_table = "\n".join(scorecard_rows)

    # ── Eventos recentes ──────────────────────────────────────────────────────
    events = db.execute(text("""
        SELECT ce.nome, ce.data_evento, c.name, ce.event_type, ce.sentiment_delta
        FROM company_events ce
        JOIN companies c ON c.id = ce.company_id
        WHERE ce.is_confirmed = true OR ce.source = 'manual'
        ORDER BY ce.data_evento DESC
        LIMIT 8
    """)).fetchall()

    events_lines = []
    for nome, data_ev, co_name, etype, delta in events:
        delta_str = f" (Δ{delta:+.1f})" if delta else ""
        events_lines.append(f"- **{nome}** ({str(data_ev)[:7]}) — {co_name}{delta_str}")
    events_context = "\n".join(events_lines) or "— Nenhum evento confirmado registrado"

    return SYSTEM_PROMPT.format(
        total_companies=len(companies_with_score),
        total_reviews=total_reviews,
        total_jobs=total_jobs,
        companies_context=companies_context,
        ranking_context=ranking_context,
        scorecard_table=scorecard_table,
        events_context=events_context,
    )


def get_query_embedding(query: str) -> list[float]:
    result = voyage_client.embed([query], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]


def retrieve_reviews(db: Session, vec_str: str) -> tuple[str, list[dict]]:
    rows = db.execute(text("""
        SELECT r.id, c.name, c.slug, r.cargo, r.avaliacao_geral,
               r.pros, r.contras, r.resumo_ia, r.sentimento_geral,
               r.data_review, r.nivel_senioridade, r.area_funcional,
               ROUND((1 - (embedding <=> CAST(:vec AS vector)))::numeric, 3) as sim
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT :lim
    """), {"vec": vec_str, "lim": RAG_LIMIT}).fetchall()

    parts, sources = [], []
    for id_, empresa, slug, cargo, nota, pros, contras, resumo, sentimento, data_r, nivel, area, sim in rows:
        header = (
            f"[Review #{id_} | {empresa} | {cargo or 'N/A'} | "
            f"{nivel or ''} | {area or ''} | ⭐{nota}/5 | "
            f"{sentimento} | {str(data_r)[:7] if data_r else ''}]"
        )
        linhas = [header]
        if resumo:  linhas.append(f"Síntese: {resumo}")
        if pros:    linhas.append(f"Positivos: {pros[:300]}")
        if contras: linhas.append(f"Negativos: {contras[:300]}")
        parts.append("\n".join(linhas))
        sources.append({
            "id":           id_,
            "empresa":      empresa,
            "empresa_slug": slug,
            "cargo":        cargo,
            "nota":         float(nota) if nota else None,
            "sentimento":   sentimento,
            "nivel":        nivel,
            "area":         area,
            "similarity":   float(sim),
            "trecho":       (contras or pros or "")[:150],
        })

    return "\n\n---\n\n".join(parts), sources


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    thread_id: str | None = None
    user_identifier: str | None = None


class FeedbackRequest(BaseModel):
    feedback: str  # "positive" | "negative"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    start = time.time()

    # 1. Resolve ou cria thread
    thread_id = req.thread_id
    if thread_id:
        if not db.execute(
            text("SELECT id FROM chat_threads WHERE id = :id"), {"id": thread_id}
        ).fetchone():
            raise HTTPException(404, "Thread não encontrado.")
    else:
        thread_id = str(uuid.uuid4())
        title = req.question[:80] + ("..." if len(req.question) > 80 else "")
        c6_id = db.execute(
            text("SELECT id FROM companies WHERE slug = 'c6_bank'")
        ).scalar()
        db.execute(text("""
            INSERT INTO chat_threads (id, title, target_company_id, user_identifier, message_count)
            VALUES (:id, :title, :cid, :user, 0)
        """), {"id": thread_id, "title": title, "cid": c6_id, "user": req.user_identifier})
        db.commit()

    # 2. Carrega histórico
    history_rows = db.execute(text("""
        SELECT role, content FROM chat_messages
        WHERE thread_id = :tid ORDER BY created_at ASC LIMIT :lim
    """), {"tid": thread_id, "lim": MAX_HISTORY * 2}).fetchall()
    history = [{"role": r[0], "content": r[1]} for r in history_rows]

    # 3. Persiste mensagem do usuário
    db.execute(text("""
        INSERT INTO chat_messages (thread_id, role, content, embedding_query)
        VALUES (:tid, 'user', :content, :query)
    """), {"tid": thread_id, "content": req.question, "query": req.question})
    db.execute(text("""
        UPDATE chat_threads
        SET message_count = message_count + 1, last_message_at = NOW(), updated_at = NOW()
        WHERE id = :id
    """), {"id": thread_id})
    db.commit()

    # 4. RAG — busca semântica em todas as empresas
    q_emb   = get_query_embedding(req.question)
    vec_str = "[" + ",".join(str(round(x, 8)) for x in q_emb) + "]"
    context, sources = retrieve_reviews(db, vec_str)
    review_ids = [s["id"] for s in sources]

    # 5. Chama Claude com system prompt de mercado completo
    system_prompt = build_system_prompt(db)
    messages = history + [{
        "role": "user",
        "content": (
            f"## Reviews relevantes recuperadas da base de dados\n\n{context}\n\n"
            f"---\n\n## Pergunta\n\n{req.question}"
        ),
    }]

    response = anthropic_client.messages.create(
        model=CHAT_MODEL,
        max_tokens=1500,
        system=system_prompt,
        messages=messages,
    )

    answer     = response.content[0].text
    tokens     = response.usage.input_tokens + response.usage.output_tokens
    latency_ms = int((time.time() - start) * 1000)

    # 6. Persiste resposta
    msg_row = db.execute(text("""
        INSERT INTO chat_messages
            (thread_id, role, content, sources, review_ids_used,
             embedding_query, tokens_used, model_used, latency_ms)
        VALUES (:tid, 'assistant', :content, :sources, :rids, :query, :tokens, :model, :lat)
        RETURNING id
    """), {
        "tid":     thread_id,
        "content": answer,
        "sources": json.dumps(sources[:5], ensure_ascii=False),
        "rids":    review_ids,
        "query":   req.question,
        "tokens":  tokens,
        "model":   CHAT_MODEL,
        "lat":     latency_ms,
    }).fetchone()

    db.execute(text("""
        UPDATE chat_threads
        SET message_count = message_count + 1, last_message_at = NOW(), updated_at = NOW()
        WHERE id = :id
    """), {"id": thread_id})
    db.commit()

    return {
        "answer":        answer,
        "thread_id":     thread_id,
        "message_id":    msg_row[0] if msg_row else None,
        "sources":       sources[:5],
        "total_sources": len(sources),
        "tokens_used":   tokens,
        "latency_ms":    latency_ms,
    }


@router.get("/chat/threads")
def list_threads(
    user_identifier: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    where  = "WHERE user_identifier = :user" if user_identifier else ""
    params: dict = {"limit": limit}
    if user_identifier:
        params["user"] = user_identifier

    rows = db.execute(text(f"""
        SELECT id, title, message_count, last_message_at, created_at
        FROM chat_threads {where}
        ORDER BY updated_at DESC LIMIT :limit
    """), params).fetchall()

    return {"threads": [
        {
            "id":              r[0],
            "title":           r[1],
            "message_count":   r[2],
            "last_message_at": str(r[3]) if r[3] else None,
            "created_at":      str(r[4]) if r[4] else None,
        }
        for r in rows
    ]}


@router.get("/chat/threads/{thread_id}/messages")
def get_thread_messages(thread_id: str, db: Session = Depends(get_db)):
    thread = db.execute(
        text("SELECT id, title, message_count FROM chat_threads WHERE id = :id"),
        {"id": thread_id},
    ).fetchone()
    if not thread:
        raise HTTPException(404, "Thread não encontrado.")

    rows = db.execute(text("""
        SELECT id, role, content, sources, tokens_used, latency_ms, feedback, created_at
        FROM chat_messages
        WHERE thread_id = :tid
        ORDER BY created_at ASC
    """), {"tid": thread_id}).fetchall()

    messages = []
    for id_, role, content, sources_raw, tokens, latency, feedback, created in rows:
        srcs = (
            sources_raw if isinstance(sources_raw, list)
            else (json.loads(sources_raw) if sources_raw else [])
        )
        messages.append({
            "id":          id_,
            "role":        role,
            "content":     content,
            "sources":     srcs,
            "tokens_used": tokens,
            "latency_ms":  latency,
            "feedback":    feedback,
            "created_at":  str(created) if created else None,
        })

    return {
        "thread_id":     thread[0],
        "title":         thread[1],
        "message_count": thread[2],
        "messages":      messages,
    }


@router.post("/chat/messages/{message_id}/feedback")
def submit_feedback(message_id: int, req: FeedbackRequest, db: Session = Depends(get_db)):
    if req.feedback not in ("positive", "negative"):
        raise HTTPException(400, "Feedback deve ser 'positive' ou 'negative'.")
    result = db.execute(text("""
        UPDATE chat_messages SET feedback = :fb
        WHERE id = :id AND role = 'assistant'
        RETURNING id
    """), {"fb": req.feedback, "id": message_id}).fetchone()
    if not result:
        raise HTTPException(404, "Mensagem não encontrada.")
    db.commit()
    return {"message_id": message_id, "feedback": req.feedback}


@router.delete("/chat/threads/{thread_id}")
def delete_thread(thread_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        text("DELETE FROM chat_threads WHERE id = :id RETURNING id"),
        {"id": thread_id},
    ).fetchone()
    if not result:
        raise HTTPException(404, "Thread não encontrado.")
    db.commit()
    return {"deleted": thread_id}


@router.get("/chat/suggestions")
def get_suggestions():
    return {"suggestions": [
        "Quais são os maiores riscos de retenção no C6 Bank?",
        "Compare o employer branding do C6 com todos os concorrentes do mercado.",
        "Em quais dimensões o iFood está à frente do C6 e o que podemos aprender?",
        "Qual empresa tem a melhor percepção de saúde mental e como replicar?",
        "Quais janelas de captação existem no mercado agora?",
        "Como está a percepção de liderança no C6 comparada ao mercado?",
        "O Banco BV tem score alto em salários — o C6 pode usar isso como diferencial?",
        "Quais problemas são exclusivos do C6 vs endêmicos do setor financeiro?",
    ]}