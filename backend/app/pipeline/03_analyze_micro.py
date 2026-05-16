#!/usr/bin/env python3
"""
Pipeline Step 03 — Análise micro por review via Claude API

Para cada review:
  • Classifica sentimento em 9 dimensões (com quote de evidência)
  • Extrai temas emergentes (não pré-definidos)
  • Detecta menções a concorrentes
  • Gera resumo estratégico em 2-3 linhas
  • Calcula intensidade emocional (1-10)

Paralelo: 5 workers simultâneos
Idempotente: pula reviews já analisadas com a mesma analysis_version
Retry: 3 tentativas com backoff exponencial em caso de erro da API

Uso:
    cd backend/
    python -m app.pipeline.03_analyze_micro

    # Rodar só para uma empresa:
    python -m app.pipeline.03_analyze_micro --empresa c6_bank

    # Forçar re-análise (nova versão):
    python -m app.pipeline.03_analyze_micro --force
"""

import sys
import json
import argparse
import time
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import text
from tqdm import tqdm
import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session, SessionLocal
from app.config import get_settings

settings = get_settings()
client   = anthropic.Anthropic(api_key=settings.anthropic_api_key)

ANALYSIS_VERSION = settings.analysis_version
MAX_WORKERS      = settings.pipeline_workers
MODEL            = "claude-haiku-4-5-20251001"  # Haiku = rápido e barato para análise em massa

# ── Prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Você é um especialista sênior em employer branding e inteligência de pessoas,
com profundo conhecimento do mercado de fintechs brasileiro.

Sua tarefa é analisar reviews de funcionários do Glassdoor e extrair insights estratégicos
estruturados. Você entende português brasileiro coloquial, gírias corporativas e ironia.

Responda SEMPRE em JSON válido, sem texto antes ou depois, sem markdown, sem backticks."""

def build_prompt(review: dict, dimensions: list[dict]) -> str:
    # Monta texto da review
    partes = []
    if review.get("titulo_review"):
        partes.append(f"Título: {review['titulo_review']}")
    if review.get("pros"):
        partes.append(f"Pontos positivos: {review['pros']}")
    if review.get("contras"):
        partes.append(f"Pontos negativos: {review['contras']}")
    if review.get("conselho_presidencia"):
        partes.append(f"Conselho à presidência: {review['conselho_presidencia']}")

    texto_review = "\n\n".join(partes) if partes else "Sem texto disponível."

    dims_desc = "\n".join(
        f'  - "{d["slug"]}": {d["description"]}'
        for d in dimensions
    )

    return f"""Analise esta review do Glassdoor de um funcionário da empresa {review.get('empresa', 'desconhecida')}.

DADOS DA REVIEW:
- Cargo: {review.get('cargo', 'Não informado')}
- Nota geral: {review.get('avaliacao_geral', 'N/A')}/5
- Status: {review.get('status_funcionario', 'Não informado')}
- Tempo na empresa: {review.get('tempo_empresa', 'Não informado')}
- Data: {review.get('data_review', 'Não informado')}

TEXTO:
{texto_review}

DIMENSÕES PARA ANALISAR:
{dims_desc}

Retorne um JSON com esta estrutura EXATA:

{{
  "resumo_ia": "string — 2 a 3 frases capturando a essência estratégica desta review para um diretor de RH",
  "sentimento_geral": "positivo" | "negativo" | "misto" | "neutro",
  "intensidade_emocional": número de 1 a 10 (1=muito calmo, 10=extremamente intenso/emocional),
  "temas_emergentes": ["tema1", "tema2", ...],
  "menciona_concorrentes": [
    {{
      "empresa": "nome da empresa mencionada",
      "contexto": "breve descrição do contexto",
      "sentimento": "positivo" | "negativo" | "neutro"
    }}
  ],
  "dimensoes": [
    {{
      "slug": "slug_da_dimensao",
      "mencionada": true | false,
      "sentiment": "positivo" | "negativo" | "misto" | "neutro",
      "intensity": número de 1 a 10,
      "evidence_quote": "trecho exato da review que justifica esta classificação (máx 150 chars)",
      "is_primary": true | false
    }}
  ]
}}

REGRAS:
1. Inclua TODAS as {len(dimensions)} dimensões no array, mesmo as não mencionadas (mencionada: false)
2. evidence_quote deve ser um trecho LITERAL da review, não uma paráfrase
3. temas_emergentes: temas específicos desta review que não se encaixam nas dimensões (ex: "Clojure nichado", "RTO novembro 2025", "layoff fev/2023")
4. intensidade_emocional: avalie a carga emocional do texto, não o conteúdo (texto neutro = 1-3, texto apaixonado/revoltado = 8-10)
5. Para reviews muito curtas ou sem texto, retorne os campos com valores padrão (mencionada: false, sentiment: neutro)
6. menciona_concorrentes: só inclua se houver menção EXPLÍCITA a outra empresa pelo nome
7. is_primary: true apenas para a dimensão que é o tema CENTRAL da review (no máximo 1-2)"""


# ── Análise de uma review ─────────────────────────────────────────────────────

def analyze_review(review_id: int, review: dict, dimensions: list[dict], max_retries: int = 3) -> dict | None:
    """Chama a Claude API e retorna o resultado estruturado."""
    prompt = build_prompt(review, dimensions)

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            raw = response.content[0].text.strip()

            # Remove possíveis backticks se o modelo os incluir
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            result = json.loads(raw)
            result["review_id"] = review_id
            return result

        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"\n  ⚠️  JSON inválido para review {review_id}: {e}")
                return None

        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"\n  ⏳ Rate limit — aguardando {wait}s...")
            time.sleep(wait)

        except anthropic.APIError as e:
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                print(f"\n  ❌ API error para review {review_id}: {e}")
                return None

    return None


# ── Persistência ──────────────────────────────────────────────────────────────

def save_analysis(result: dict, dimension_map: dict[str, int]):
    """Salva o resultado da análise no banco (review + review_dimensions)."""
    if not result:
        return False

    review_id = result["review_id"]

    # Usa sessão própria para cada thread (thread-safe)
    session = SessionLocal()
    try:
        # Atualiza review com análise micro
        session.execute(
            text("""
                UPDATE reviews SET
                    analyzed_at              = :analyzed_at,
                    analysis_version         = :analysis_version,
                    sentimento_geral         = :sentimento_geral,
                    intensidade_emocional    = :intensidade_emocional,
                    temas_emergentes         = :temas_emergentes,
                    menciona_concorrentes    = :menciona_concorrentes,
                    resumo_ia                = :resumo_ia
                WHERE id = :review_id
            """),
            {
                "review_id":            review_id,
                "analyzed_at":          datetime.now(timezone.utc),
                "analysis_version":     ANALYSIS_VERSION,
                "sentimento_geral":     result.get("sentimento_geral", "neutro"),
                "intensidade_emocional": result.get("intensidade_emocional", 5),
                "temas_emergentes":     json.dumps(result.get("temas_emergentes", []), ensure_ascii=False),
                "menciona_concorrentes": json.dumps(result.get("menciona_concorrentes", []), ensure_ascii=False),
                "resumo_ia":            result.get("resumo_ia", ""),
            },
        )

        # Remove dimensões antigas desta versão (idempotência)
        session.execute(
            text("""
                DELETE FROM review_dimensions
                WHERE review_id = :review_id AND analysis_version = :version
            """),
            {"review_id": review_id, "version": ANALYSIS_VERSION},
        )

        # Insere dimensões
        dims = result.get("dimensoes", [])
        dim_rows = []
        for d in dims:
            slug = d.get("slug")
            dim_id = dimension_map.get(slug)
            if not dim_id or not d.get("mencionada", False):
                continue

            dim_rows.append({
                "review_id":        review_id,
                "dimension_id":     dim_id,
                "analysis_version": ANALYSIS_VERSION,
                "sentiment":        d.get("sentiment", "neutro"),
                "intensity":        d.get("intensity", 5),
                "evidence_quote":   (d.get("evidence_quote") or "")[:500],
                "confidence":       0.85,  # confiança padrão para Claude
                "is_primary":       d.get("is_primary", False),
            })

        if dim_rows:
            session.execute(
                text("""
                    INSERT INTO review_dimensions
                        (review_id, dimension_id, analysis_version, sentiment,
                         intensity, evidence_quote, confidence, is_primary)
                    VALUES
                        (:review_id, :dimension_id, :analysis_version, :sentiment,
                         :intensity, :evidence_quote, :confidence, :is_primary)
                """),
                dim_rows,
            )

        session.commit()
        return True

    except Exception as e:
        session.rollback()
        print(f"\n  ❌ Erro ao salvar review {review_id}: {e}")
        return False
    finally:
        session.close()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--empresa", help="Slug da empresa: c6_bank | nubank")
    parser.add_argument("--force",   action="store_true", help="Re-analisa reviews já analisadas")
    parser.add_argument("--limit",   type=int, default=0, help="Limitar número de reviews (teste)")
    args = parser.parse_args()

    print("=" * 65)
    print("  Pipeline 03 — Análise micro via Claude API")
    print(f"  Model: {MODEL}  |  Version: {ANALYSIS_VERSION}  |  Workers: {MAX_WORKERS}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:
        # Carrega dimensões
        dims_raw = session.execute(
            text("SELECT id, slug, name, description FROM dimensions WHERE is_active = true ORDER BY display_order")
        ).fetchall()
        dimensions    = [{"id": r[0], "slug": r[1], "name": r[2], "description": r[3]} for r in dims_raw]
        dimension_map = {d["slug"]: d["id"] for d in dimensions}
        print(f"\n✅ {len(dimensions)} dimensões carregadas")

        # Monta query de reviews pendentes
        where_clauses = []
        params: dict = {}

        if not args.force:
            where_clauses.append(
                "(analysis_version IS NULL OR analysis_version != :version)"
            )
            params["version"] = ANALYSIS_VERSION

        if args.empresa:
            where_clauses.append("""
                company_id = (SELECT id FROM companies WHERE slug = :slug)
            """)
            params["slug"] = args.empresa

        # Não processa reviews de eventos e sem texto útil
        where_clauses.append("is_event_review = false")
        where_clauses.append("(pros IS NOT NULL OR contras IS NOT NULL OR titulo_review IS NOT NULL)")

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
            SELECT r.id, r.cargo, r.avaliacao_geral, r.status_funcionario,
                   r.tempo_empresa, r.data_review, r.titulo_review,
                   r.pros, r.contras, r.conselho_presidencia,
                   c.name as empresa
            FROM reviews r
            JOIN companies c ON c.id = r.company_id
            {where_sql}
            ORDER BY r.company_id, r.data_review DESC NULLS LAST
        """

        if args.limit:
            query += f" LIMIT {args.limit}"

        rows = session.execute(text(query), params).fetchall()

    print(f"📋 Reviews para analisar: {len(rows)}")

    if not rows:
        print("  ✅ Nada a analisar. Use --force para re-analisar.")
        return

    # Estima custo e tempo
    est_minutes = len(rows) / (MAX_WORKERS * 3)  # ~3 reviews/worker/min
    print(f"⏱️  Estimativa: ~{est_minutes:.0f} min com {MAX_WORKERS} workers\n")

    # Prepara dicionários para passar às threads
    reviews_dict = []
    for row in rows:
        (id_, cargo, nota, status, tempo, data_r, titulo,
         pros, contras, conselho, empresa) = row
        reviews_dict.append({
            "id": id_,
            "data": {
                "empresa":             empresa,
                "cargo":               cargo,
                "avaliacao_geral":     nota,
                "status_funcionario":  status,
                "tempo_empresa":       tempo,
                "data_review":         str(data_r) if data_r else None,
                "titulo_review":       titulo,
                "pros":                pros,
                "contras":             contras,
                "conselho_presidencia": conselho,
            }
        })

    # ── Processamento paralelo ──
    success = 0
    failed  = 0
    pbar    = tqdm(total=len(reviews_dict), desc="  Analisando", unit="review")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                analyze_review,
                r["id"], r["data"], dimensions
            ): r["id"]
            for r in reviews_dict
        }

        for future in as_completed(futures):
            review_id = futures[future]
            try:
                result = future.result()
                if result and save_analysis(result, dimension_map):
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"\n  ❌ Erro inesperado review {review_id}: {e}")
                failed += 1
            finally:
                pbar.update(1)
                pbar.set_postfix({"ok": success, "err": failed})

    pbar.close()

    # ── Relatório final ──
    print(f"\n{'=' * 65}")
    print(f"  ✅ Análise micro concluída")
    print(f"     Sucesso:  {success:,}")
    print(f"     Falhas:   {failed:,}")
    print(f"     Total:    {len(reviews_dict):,}")
    print(f"{'=' * 65}")
    print(f"\n🚀 Próximo passo: python -m app.pipeline.04_aggregate")


if __name__ == "__main__":
    main()