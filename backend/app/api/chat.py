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
RAG_LIMIT       = 10
MAX_HISTORY     = 10

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Você é um consultor sênior especializado em Employer Branding e estratégia de talentos, \
contratado exclusivamente pelo **C6 Bank** para apoiar decisões de captação e retenção.

## Contexto do projeto
Você tem acesso a uma base de dados proprietária com:
- **{total_c6} reviews reais** de funcionários e ex-funcionários do C6 Bank no Glassdoor
- **{total_nu} reviews reais** do Nubank — principal concorrente de talentos
- **{total_jobs} vagas do LinkedIn** de ambas as empresas, com skills mapeadas
- Análise em 9 dimensões: Liderança, Cultura, Salário, Modelo de Trabalho, Crescimento, Saúde Mental, Diversidade, Stack Técnica e Propósito

## Scorecard atual (score 0–10)
| Dimensão | C6 Bank | Nubank | |
|----------|---------|--------|---|
{scorecard_table}

## Eventos recentes relevantes
{events_context}

## Sua missão
Ajudar o C6 Bank a:
1. **Captar talentos** insatisfeitos com o Nubank (especialmente pelo RTO de nov/2025)
2. **Reter funcionários** endereçando os drivers reais de saída identificados nas reviews
3. **Fechar gaps** entre o que as vagas prometem e o que os funcionários vivem
4. **Comunicar vantagens reais** do C6 que estão sendo subutilizadas (ex: diversidade 5.5 vs 1.9)

## Como responder
- Você TEM dados do Nubank — use-os ativamente para comparações quando relevante
- Seja direto e estratégico — fale como consultor sênior, não como chatbot genérico
- Cite trechos literais das reviews entre aspas como evidência
- Use markdown: **negrito** para pontos críticos, ## para seções, listas para ações, respostas didáticas e profissionais
- Respostas entre 3–6 parágrafos, ou lista estruturada quando mais útil
- Responda SEMPRE em português brasileiro
- Se não houver evidência suficiente nas reviews fornecidas, diga e sugira o que faltaria"""


def build_system_prompt(db: Session) -> str:
    counts = db.execute(text("""
        SELECT c.slug, COUNT(*) FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.is_event_review = false AND r.analysis_version IS NOT NULL
        GROUP BY c.slug
    """)).fetchall()
    totals = {r[0]: r[1] for r in counts}

    total_jobs = db.execute(text("SELECT COUNT(*) FROM jobs")).scalar() or 0

    dims = db.execute(text("""
        SELECT d.name, s1.sentiment_score, s2.sentiment_score
        FROM dimensions d
        LEFT JOIN company_dimension_stats s1
            ON s1.dimension_id = d.id AND s1.period = 'all'
            AND s1.analysis_version = 'v1'
            AND s1.company_id = (SELECT id FROM companies WHERE slug = 'c6_bank')
        LEFT JOIN company_dimension_stats s2
            ON s2.dimension_id = d.id AND s2.period = 'all'
            AND s2.analysis_version = 'v1'
            AND s2.company_id = (SELECT id FROM companies WHERE slug = 'nubank')
        WHERE d.is_active = true ORDER BY d.display_order
    """)).fetchall()

    rows = []
    for name, c6_s, nu_s in dims:
        c6v = f"{float(c6_s):.1f}" if c6_s else "N/A"
        nuv = f"{float(nu_s):.1f}" if nu_s else "N/A"
        diff = (float(c6_s) - float(nu_s)) if (c6_s and nu_s) else 0
        arrow = "✅ C6" if diff > 0.5 else ("🟣 Nu" if diff < -0.5 else "⚖️ Empate")
        rows.append(f"| {name} | {c6v} | {nuv} | {arrow} |")

    events = db.execute(text("""
        SELECT ce.nome, ce.data_evento, c.name
        FROM company_events ce JOIN companies c ON c.id = ce.company_id
        WHERE ce.is_confirmed = true ORDER BY ce.data_evento DESC LIMIT 6
    """)).fetchall()
    events_ctx = "\n".join(f"- **{e[0]}** ({str(e[1])[:7]}) — {e[2]}" for e in events) or "—"

    return SYSTEM_PROMPT.format(
        total_c6=totals.get("c6_bank", 0),
        total_nu=totals.get("nubank", 0),
        total_jobs=total_jobs,
        scorecard_table="\n".join(rows),
        events_context=events_ctx,
    )


def get_query_embedding(query: str) -> list[float]:
    result = voyage_client.embed([query], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]


def retrieve_reviews(db: Session, vec_str: str) -> tuple[str, list[dict]]:
    rows = db.execute(text("""
        SELECT r.id, c.name, r.cargo, r.avaliacao_geral,
               r.pros, r.contras, r.resumo_ia, r.sentimento_geral,
               r.data_review, r.nivel_senioridade, r.area_funcional,
               ROUND((1 - (embedding <=> CAST(:vec AS vector)))::numeric, 3) as sim
        FROM reviews r JOIN companies c ON c.id = r.company_id
        WHERE r.embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT :lim
    """), {"vec": vec_str, "lim": RAG_LIMIT}).fetchall()

    parts, sources = [], []
    for id_, empresa, cargo, nota, pros, contras, resumo, sentimento, data_r, nivel, area, sim in rows:
        header = f"[Review #{id_} | {empresa} | {cargo or 'N/A'} | {nivel or ''} | {area or ''} | ⭐{nota}/5 | {sentimento} | {str(data_r)[:7] if data_r else ''}]"
        linhas = [header]
        if resumo:  linhas.append(f"Síntese: {resumo}")
        if pros:    linhas.append(f"Positivos: {pros[:300]}")
        if contras: linhas.append(f"Negativos: {contras[:300]}")
        parts.append("\n".join(linhas))
        sources.append({
            "id": id_, "empresa": empresa, "cargo": cargo,
            "nota": float(nota) if nota else None, "sentimento": sentimento,
            "nivel": nivel, "area": area, "similarity": float(sim),
            "trecho": (contras or pros or "")[:150],
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
        if not db.execute(text("SELECT id FROM chat_threads WHERE id = :id"), {"id": thread_id}).fetchone():
            raise HTTPException(404, "Thread não encontrado.")
    else:
        thread_id = str(uuid.uuid4())
        title = req.question[:80] + ("..." if len(req.question) > 80 else "")
        c6_id = db.execute(text("SELECT id FROM companies WHERE slug = 'c6_bank'")).scalar()
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
    db.execute(text("UPDATE chat_threads SET message_count = message_count + 1, last_message_at = NOW(), updated_at = NOW() WHERE id = :id"), {"id": thread_id})
    db.commit()

    # 4. RAG
    q_emb   = get_query_embedding(req.question)
    vec_str = "[" + ",".join(str(round(x, 8)) for x in q_emb) + "]"
    context, sources = retrieve_reviews(db, vec_str)
    review_ids = [s["id"] for s in sources]

    # 5. Chama Claude
    system_prompt = build_system_prompt(db)
    messages = history + [{
        "role": "user",
        "content": f"## Reviews relevantes da base de dados\n\n{context}\n\n---\n\n## Pergunta\n\n{req.question}"
    }]

    response = anthropic_client.messages.create(
        model=CHAT_MODEL, max_tokens=1500,
        system=system_prompt, messages=messages,
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
        "tid": thread_id, "content": answer,
        "sources": json.dumps(sources[:5], ensure_ascii=False),
        "rids": review_ids, "query": req.question,
        "tokens": tokens, "model": CHAT_MODEL, "lat": latency_ms,
    }).fetchone()

    db.execute(text("UPDATE chat_threads SET message_count = message_count + 1, last_message_at = NOW(), updated_at = NOW() WHERE id = :id"), {"id": thread_id})
    db.commit()

    return {
        "answer": answer, "thread_id": thread_id,
        "message_id": msg_row[0] if msg_row else None,
        "sources": sources[:5], "total_sources": len(sources),
        "tokens_used": tokens, "latency_ms": latency_ms,
    }


@router.get("/chat/threads")
def list_threads(user_identifier: str | None = None, limit: int = 20, db: Session = Depends(get_db)):
    where  = "WHERE user_identifier = :user" if user_identifier else ""
    params = {"limit": limit}
    if user_identifier: params["user"] = user_identifier

    rows = db.execute(text(f"""
        SELECT id, title, message_count, last_message_at, created_at
        FROM chat_threads {where} ORDER BY updated_at DESC LIMIT :limit
    """), params).fetchall()

    return {"threads": [
        {"id": r[0], "title": r[1], "message_count": r[2],
         "last_message_at": str(r[3]) if r[3] else None,
         "created_at": str(r[4]) if r[4] else None}
        for r in rows
    ]}


@router.get("/chat/threads/{thread_id}/messages")
def get_thread_messages(thread_id: str, db: Session = Depends(get_db)):
    thread = db.execute(
        text("SELECT id, title, message_count FROM chat_threads WHERE id = :id"),
        {"id": thread_id}
    ).fetchone()
    if not thread:
        raise HTTPException(404, "Thread não encontrado.")

    rows = db.execute(text("""
        SELECT id, role, content, sources, tokens_used, latency_ms, feedback, created_at
        FROM chat_messages WHERE thread_id = :tid ORDER BY created_at ASC
    """), {"tid": thread_id}).fetchall()

    messages = []
    for id_, role, content, sources_raw, tokens, latency, feedback, created in rows:
        srcs = sources_raw if isinstance(sources_raw, list) else (json.loads(sources_raw) if sources_raw else [])
        messages.append({
            "id": id_, "role": role, "content": content, "sources": srcs,
            "tokens_used": tokens, "latency_ms": latency,
            "feedback": feedback, "created_at": str(created) if created else None,
        })

    return {"thread_id": thread[0], "title": thread[1], "message_count": thread[2], "messages": messages}


@router.post("/chat/messages/{message_id}/feedback")
def submit_feedback(message_id: int, req: FeedbackRequest, db: Session = Depends(get_db)):
    if req.feedback not in ("positive", "negative"):
        raise HTTPException(400, "Feedback deve ser 'positive' ou 'negative'.")
    result = db.execute(text("""
        UPDATE chat_messages SET feedback = :fb WHERE id = :id AND role = 'assistant' RETURNING id
    """), {"fb": req.feedback, "id": message_id}).fetchone()
    if not result:
        raise HTTPException(404, "Mensagem não encontrada.")
    db.commit()
    return {"message_id": message_id, "feedback": req.feedback}


@router.delete("/chat/threads/{thread_id}")
def delete_thread(thread_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        text("DELETE FROM chat_threads WHERE id = :id RETURNING id"), {"id": thread_id}
    ).fetchone()
    if not result:
        raise HTTPException(404, "Thread não encontrado.")
    db.commit()
    return {"deleted": thread_id}


@router.get("/chat/suggestions")
def get_suggestions():
    return {"suggestions": [
        "Quais são os maiores riscos de retenção no C6 Bank?",
        "Como aproveitar o RTO do Nubank para captar talentos sêniors?",
        "O que engenheiros sêniors reclamam no C6 Bank?",
        "Em quais dimensões o C6 Bank supera o Nubank como empregador?",
        "Quais 3 ações tomar nos próximos 90 dias para melhorar o employer branding?",
        "Como está a percepção de liderança no C6 comparado ao Nubank?",
        "Qual o perfil dos funcionários que saíram do C6 Bank em 2024?",
        "O que o C6 pode aprender com os pontos fortes do Nubank em stack técnica?",
    ]}