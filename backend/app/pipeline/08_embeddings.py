#!/usr/bin/env python3
"""
Pipeline Step 08 — Embeddings vetoriais para RAG

Gera embeddings vector(1024) para cada review usando a API Voyage AI
(via SDK voyageai) e persiste na coluna `embedding` da tabela reviews.

Modelo: voyage-3 (1024 dimensões, melhor custo-benefício para RAG)

Idempotente: pula reviews que já têm embedding.
Processa em batches de 128 textos por chamada.

Uso:
    cd backend/
    pip install voyageai
    python -m app.pipeline.08_embeddings

    # Forçar re-geração:
    python -m app.pipeline.08_embeddings --force

    # Só uma empresa:
    python -m app.pipeline.08_embeddings --empresa c6_bank
"""

import sys
import argparse
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
from tqdm import tqdm
import voyageai

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session, SessionLocal
from app.config import get_settings

settings = get_settings()

EMBEDDING_MODEL = "voyage-3"
BATCH_SIZE      = 10    # pequeno para respeitar rate limit do free tier
MAX_CHARS       = 4000  # trunca textos muito longos


# ── Setup do cliente Voyage ───────────────────────────────────────────────────

try:
    
    voyage_api_key = getattr(settings, "voyage_api_key", None) or settings.anthropic_api_key
    voyage_client = voyageai.Client(api_key=voyage_api_key)
    print(f"✅ voyageai SDK carregado")
except ImportError:
    print("❌ voyageai não instalado. Rode: pip install voyageai")
    sys.exit(1)


# ── Monta texto para embedding ────────────────────────────────────────────────

def build_embedding_text(row: dict) -> str:
    partes = []

    if row.get("empresa"):
        partes.append(f"Empresa: {row['empresa']}")
    if row.get("cargo"):
        partes.append(f"Cargo: {row['cargo']}")
    if row.get("avaliacao_geral"):
        partes.append(f"Nota: {row['avaliacao_geral']}/5")
    if row.get("titulo_review"):
        partes.append(f"Título: {row['titulo_review']}")
    if row.get("pros"):
        partes.append(f"Pontos positivos: {row['pros']}")
    if row.get("contras"):
        partes.append(f"Pontos negativos: {row['contras']}")
    if row.get("conselho_presidencia"):
        partes.append(f"Conselho: {row['conselho_presidencia']}")
    if row.get("resumo_ia"):
        partes.append(f"Análise: {row['resumo_ia']}")

    texto = "\n".join(partes)
    if len(texto) > MAX_CHARS:
        texto = texto[:MAX_CHARS] + "..."
    return texto


# ── Geração de embeddings em batch ───────────────────────────────────────────

def generate_embeddings_batch(texts: list[str], max_retries: int = 3) -> list[list[float]] | None:
    for attempt in range(max_retries):
        try:
            result = voyage_client.embed(
                texts,
                model=EMBEDDING_MODEL,
                input_type="document",
            )
            return result.embeddings

        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err:
                wait = 30 * (attempt + 1)
                print(f"\n  ⏳ Rate limit — aguardando {wait}s...")
                time.sleep(wait)
            elif attempt < max_retries - 1:
                print(f"\n  ⚠️  Erro tentativa {attempt + 1}: {e}")
                time.sleep(5 * (attempt + 1))
            else:
                print(f"\n  ❌ Falha após {max_retries} tentativas: {e}")
                return None

    return None


# ── Persistência ──────────────────────────────────────────────────────────────

def save_embeddings(review_ids: list[int], embeddings: list[list[float]]):
    session = SessionLocal()
    try:
        for review_id, embedding in zip(review_ids, embeddings):
            vec_str = "[" + ",".join(str(round(x, 8)) for x in embedding) + "]"
            session.execute(
                text("UPDATE reviews SET embedding = CAST(:emb AS vector) WHERE id = :id"),
                {"emb": vec_str, "id": review_id}
            )
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"\n  ❌ Erro ao salvar embeddings: {e}")
    finally:
        session.close()


# ── Índice vetorial ───────────────────────────────────────────────────────────

def recreate_vector_index(session):
    try:
        n = session.execute(
            text("SELECT COUNT(*) FROM reviews WHERE embedding IS NOT NULL")
        ).scalar()

        if n < 50:
            print(f"  ⚠️  Poucos embeddings ({n}) — pulando criação de índice")
            return

        lists = max(10, int(n ** 0.5))
        print(f"  🔧 Criando índice IVFFlat (lists={lists}) para {n} vetores...")

        session.execute(text("DROP INDEX IF EXISTS ix_reviews_embedding"))
        session.execute(text(f"""
            CREATE INDEX ix_reviews_embedding
            ON reviews
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = {lists})
        """))
        session.commit()
        print(f"  ✅ Índice criado com sucesso")
    except Exception as e:
        session.rollback()
        print(f"  ⚠️  Índice não criado: {e}")


# ── Teste de busca semântica ──────────────────────────────────────────────────

def demo_semantic_search(session):
    print(f"\n{'=' * 65}")
    print(f"  🔍 Demonstração de busca semântica (RAG)")
    print(f"{'=' * 65}")

    queries = [
        "burnout causado por liderança despreparada",
        "oportunidade de captação RTO Nubank modelo híbrido",
        "vantagem do C6 Bank em diversidade e inclusão",
    ]

    for query_text in queries:
        result = voyage_client.embed(
            [query_text],
            model=EMBEDDING_MODEL,
            input_type="query",  # "query" para buscas, "document" para indexação
        )
        vec_str = "[" + ",".join(str(round(x, 8)) for x in result.embeddings[0]) + "]"

        rows = session.execute(text("""
            SELECT r.id, c.name, r.cargo, r.avaliacao_geral,
                   LEFT(COALESCE(r.contras, r.pros, ''), 120) as trecho,
                   ROUND((1 - (embedding <=> CAST(:vec AS vector)))::numeric, 3) as similarity
            FROM reviews r
            JOIN companies c ON c.id = r.company_id
            WHERE r.embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT 3
        """), {"vec": vec_str}).fetchall()

        print(f"\n  📌 Query: \"{query_text}\"")
        for id_, empresa, cargo, nota, trecho, sim in rows:
            print(f"    [{sim}] {empresa} | {cargo or 'N/A'} | ⭐{nota}")
            print(f"           \"{trecho}...\"")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--empresa", help="Slug: c6_bank | nubank")
    parser.add_argument("--force",   action="store_true",
                        help="Re-gera embeddings já existentes")
    args = parser.parse_args()

    print("=" * 65)
    print(f"  Pipeline 08 — Embeddings vetoriais ({EMBEDDING_MODEL})")
    print(f"  Batch: {BATCH_SIZE} | Max chars: {MAX_CHARS}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:
        where  = ["(pros IS NOT NULL OR contras IS NOT NULL)",
                  "is_event_review = false"]
        params: dict = {}

        if not args.force:
            where.append("embedding IS NULL")

        if args.empresa:
            where.append("company_id = (SELECT id FROM companies WHERE slug = :slug)")
            params["slug"] = args.empresa

        rows = session.execute(text(f"""
            SELECT r.id, r.pros, r.contras, r.titulo_review,
                   r.conselho_presidencia, r.resumo_ia,
                   r.cargo, r.avaliacao_geral,
                   c.name as empresa
            FROM reviews r
            JOIN companies c ON c.id = r.company_id
            WHERE {' AND '.join(where)}
            ORDER BY r.company_id, r.id
        """), params).fetchall()

    total = len(rows)
    print(f"\n📋 Reviews para processar: {total}")

    if not total:
        print("  ✅ Todas as reviews já têm embeddings. Use --force para re-gerar.")
        # Mesmo sem processar, faz demo se já houver embeddings
        with get_session() as session:
            n_emb = session.execute(
                text("SELECT COUNT(*) FROM reviews WHERE embedding IS NOT NULL")
            ).scalar()
            if n_emb > 0:
                demo_semantic_search(session)
        return

    # Custo estimado (voyage-3: $0.06/1M tokens, ~200 tokens/review)
    est_tokens = total * 200
    est_cost   = est_tokens / 1_000_000 * 0.06
    print(f"💰 Custo estimado: ~{est_tokens:,} tokens | ~${est_cost:.4f} USD\n")

    # Prepara dados
    review_data = []
    for row in rows:
        id_, pros, contras, titulo, conselho, resumo, cargo, nota, empresa = row
        texto = build_embedding_text({
            "empresa": empresa, "cargo": cargo,
            "avaliacao_geral": nota, "titulo_review": titulo,
            "pros": pros, "contras": contras,
            "conselho_presidencia": conselho, "resumo_ia": resumo,
        })
        review_data.append({"id": id_, "texto": texto})

    # Batches
    batches = [review_data[i:i + BATCH_SIZE]
               for i in range(0, len(review_data), BATCH_SIZE)]

    print(f"📦 {len(batches)} batches de até {BATCH_SIZE} reviews\n")

    success, failed = 0, 0
    pbar = tqdm(batches, desc="  Embeddings", unit="batch")

    for batch in pbar:
        texts      = [r["texto"] for r in batch]
        ids        = [r["id"]    for r in batch]
        embeddings = generate_embeddings_batch(texts)

        if embeddings and len(embeddings) == len(ids):
            save_embeddings(ids, embeddings)
            success += len(ids)
        else:
            failed += len(ids)

        pbar.set_postfix({"ok": success, "err": failed})
        time.sleep(3)  # pausa de 3s entre batches para free tier

    pbar.close()

    # Recria índice
    print(f"\n  🔧 Recriando índice vetorial...")
    with get_session() as session:
        recreate_vector_index(session)

    # Demo de busca
    with get_session() as session:
        demo_semantic_search(session)

    print(f"\n{'=' * 65}")
    print(f"  ✅ Embeddings concluídos")
    print(f"     Sucesso:  {success:,}")
    print(f"     Falhas:   {failed:,}")
    print(f"{'=' * 65}")
    print(f"\n🎉 Banco 100% pronto para RAG!")
    print(f"   Próximo passo: python -m app.api (FastAPI)")


if __name__ == "__main__":
    main()