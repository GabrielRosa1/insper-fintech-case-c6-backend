from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from pydantic import BaseModel
import anthropic, voyageai, os, json
from dotenv import load_dotenv
load_dotenv()

router = APIRouter(tags=["chat"])

anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
voyage_client    = voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY", os.environ["ANTHROPIC_API_KEY"]))

EMBEDDING_MODEL = "voyage-3"
CHAT_MODEL      = "claude-haiku-4-5-20251001"

class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []

def get_query_embedding(text_: str) -> list[float]:
    result = voyage_client.embed([text_], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]

@router.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    # 1. Gera embedding da pergunta
    q_emb = get_query_embedding(req.question)
    vec_str = "[" + ",".join(str(round(x, 8)) for x in q_emb) + "]"

    # 2. Busca as 8 reviews mais relevantes via similaridade
    results = db.execute(text("""
        SELECT r.id, c.name as empresa, r.cargo, r.avaliacao_geral,
               r.pros, r.contras, r.resumo_ia,
               r.sentimento_geral, r.data_review,
               ROUND((1 - (embedding <=> CAST(:vec AS vector)))::numeric, 3) as similarity
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT 8
    """), {"vec": vec_str}).fetchall()

    # 3. Monta contexto com as reviews encontradas
    context_parts = []
    sources = []
    for row in results:
        id_, empresa, cargo, nota, pros, contras, resumo, sentimento, data_r, sim = row
        texto = f"[Review #{id_} — {empresa} | {cargo or 'N/A'} | ⭐{nota} | {sentimento}]\n"
        if resumo:
            texto += f"Análise: {resumo}\n"
        if pros:
            texto += f"Positivos: {pros[:200]}\n"
        if contras:
            texto += f"Negativos: {contras[:200]}\n"
        context_parts.append(texto)
        sources.append({
            "id": id_, "empresa": empresa, "cargo": cargo,
            "nota": nota, "sentimento": sentimento,
            "similarity": float(sim),
            "trecho": (contras or pros or "")[:120],
        })

    context = "\n---\n".join(context_parts)

    # 4. Chama Claude com o contexto RAG
    system = """Você é um consultor sênior de employer branding do C6 Bank.
Responda perguntas sobre captação e retenção de talentos baseando-se nas reviews fornecidas.
Seja direto, específico e cite evidências das reviews quando relevante.
Responda sempre em português brasileiro.
Quando citar uma review, mencione a empresa e o cargo.
Mantenha respostas entre 3-6 parágrafos."""

    messages = req.history + [
        {"role": "user", "content": f"Contexto das reviews relevantes:\n{context}\n\nPergunta: {req.question}"}
    ]

    response = anthropic_client.messages.create(
        model=CHAT_MODEL,
        max_tokens=1000,
        system=system,
        messages=messages,
    )

    answer = response.content[0].text

    return {
        "answer": answer,
        "sources": sources[:5],
        "total_sources": len(sources),
    }

@router.get("/chat/suggestions")
def get_suggestions():
    return {
        "suggestions": [
            "Quais são os maiores riscos de retenção no C6 Bank?",
            "Como o C6 pode aproveitar o RTO do Nubank para captar talentos?",
            "O que os engenheiros sêniors reclamam no C6 Bank?",
            "Onde o C6 Bank é melhor que o Nubank como empregador?",
            "Quais ações tomar nos próximos 90 dias para melhorar o employer branding?",
            "Como está a percepção de liderança no C6 comparado ao Nubank?",
        ]
    }