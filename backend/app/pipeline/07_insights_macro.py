#!/usr/bin/env python3
"""
Pipeline Step 07 — Insights Estratégicos via Claude Sonnet

Recebe todo o contexto agregado e gera insights estratégicos
acionáveis para o C-level do C6 Bank.

Gera:
  • Oportunidades de captação (ex: talentos saindo do Nubank pelo RTO)
  • Riscos de retenção (ex: liderança, burnout)
  • Gaps discurso vs realidade
  • Vantagens competitivas do C6
  • Pontos cegos
  • Benchmarks positivos do Nubank
  • Plano de ação priorizado por impacto × esforço

Cada insight tem:
  • headline impactante para C-level
  • descrição completa com análise
  • ação recomendada concreta
  • prazo e responsável
  • evidências citadas das reviews
  • score de impacto × esforço

Uso:
    cd backend/
    python -m app.pipeline.07_insights_macro
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import text
import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session
from app.config import get_settings

settings = get_settings()
client   = anthropic.Anthropic(api_key=settings.anthropic_api_key)

ANALYSIS_VERSION = settings.analysis_version
MODEL            = "claude-sonnet-4-5"

SYSTEM_PROMPT = """Você é um consultor sênior de employer branding e estratégia de pessoas,
especializado no mercado de fintechs brasileiro. Você tem profundo conhecimento de C6 Bank e Nubank.

Sua tarefa é analisar dados consolidados de reviews do Glassdoor e vagas do LinkedIn
para gerar insights estratégicos acionáveis para o C-level do C6 Bank.

Os insights devem ser:
- ESPECÍFICOS: baseados nos dados fornecidos, não em generalidades
- ACIONÁVEIS: com recomendações concretas e prazo
- IMPACTANTES: focados no que realmente move o ponteiro de captação e retenção
- HONESTOS: não suavize problemas críticos

Responda SEMPRE em JSON válido, sem markdown, sem backticks, sem texto antes ou depois."""


def safe_json_loads(val):
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return []


# ── Coleta contexto completo do banco ────────────────────────────────────────

def build_context(session) -> dict:
    """Monta o contexto completo para o Claude Sonnet."""

    # Companies
    companies = session.execute(
        text("SELECT id, slug, name, is_target FROM companies WHERE is_active = true")
    ).fetchall()
    company_map = {slug: {"id": id_, "name": name, "is_target": is_target}
                   for id_, slug, name, is_target in companies}

    c6_id = company_map["c6_bank"]["id"]
    nu_id = company_map["nubank"]["id"]

    # Dimensions
    dims = session.execute(
        text("SELECT id, slug, name FROM dimensions WHERE is_active = true ORDER BY display_order")
    ).fetchall()
    dim_map = {id_: {"slug": slug, "name": name} for id_, slug, name in dims}

    # Stats gerais por empresa
    def get_company_summary(company_id: int) -> dict:
        row = session.execute(text("""
            SELECT COUNT(*),
                   ROUND(AVG(avaliacao_geral)::numeric, 2),
                   SUM(CASE WHEN sentimento_geral = 'positivo' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sentimento_geral = 'negativo' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sentimento_geral = 'misto'    THEN 1 ELSE 0 END)
            FROM reviews
            WHERE company_id = :cid
              AND is_event_review = false
              AND analysis_version IS NOT NULL
        """), {"cid": company_id}).fetchone()

        total, avg_nota, pos, neg, mix = row
        return {
            "total_reviews":  total,
            "avg_nota":       float(avg_nota) if avg_nota else 0,
            "pct_positivo":   round((pos or 0) / total * 100, 1) if total else 0,
            "pct_negativo":   round((neg or 0) / total * 100, 1) if total else 0,
            "pct_misto":      round((mix or 0) / total * 100, 1) if total else 0,
        }

    # Stats por dimensão
    def get_dimension_stats(company_id: int) -> list:
        rows = session.execute(text("""
            SELECT d.name, d.slug, s.sentiment_score, s.total_mentions,
                   s.positive_count, s.negative_count, s.mention_rate,
                   s.top_negative_quotes, s.top_positive_quotes, s.top_themes
            FROM company_dimension_stats s
            JOIN dimensions d ON d.id = s.dimension_id
            WHERE s.company_id = :cid
              AND s.period = 'all'
              AND s.analysis_version = :v
            ORDER BY d.display_order
        """), {"cid": company_id, "v": ANALYSIS_VERSION}).fetchall()

        result = []
        for row in rows:
            (name, slug, score, mentions, pos, neg, rate,
             neg_q, pos_q, themes) = row
            result.append({
                "dimensao":          name,
                "slug":              slug,
                "score":             float(score) if score else 0,
                "total_mencoes":     mentions,
                "pct_negativo":      round((neg or 0) / mentions * 100, 1) if mentions else 0,
                "pct_positivo":      round((pos or 0) / mentions * 100, 1) if mentions else 0,
                "taxa_mencao":       float(rate) if rate else 0,
                "top_quotes_neg":    safe_json_loads(neg_q)[:1],
                "top_quotes_pos":    safe_json_loads(pos_q)[:1],
                "top_temas":         safe_json_loads(themes)[:3],
            })
        return result

    # Top temas emergentes
    def get_top_temas(company_id: int, limit: int = 10) -> list:
        rows = session.execute(text("""
            SELECT temas_emergentes FROM reviews
            WHERE company_id = :cid
              AND is_event_review = false
              AND temas_emergentes IS NOT NULL
              AND analysis_version IS NOT NULL
        """), {"cid": company_id}).fetchall()

        from collections import Counter
        all_temas = []
        for (t,) in rows:
            all_temas.extend(safe_json_loads(t))
        return [{"tema": t, "frequencia": c}
                for t, c in Counter(all_temas).most_common(limit)]

    # Eventos
    def get_events(company_id: int) -> list:
        rows = session.execute(text("""
            SELECT nome, event_type, data_evento, sentiment_delta, source, is_confirmed
            FROM company_events
            WHERE company_id = :cid
              AND (is_confirmed = true OR source = 'manual')
            ORDER BY data_evento
        """), {"cid": company_id}).fetchall()
        return [
            {
                "nome":             nome,
                "tipo":             etype,
                "data":             str(data) if data else None,
                "delta_sentimento": float(delta) if delta else None,
                "confirmado":       confirmed,
            }
            for nome, etype, data, delta, source, confirmed in rows
        ]

    # Gaps
    def get_gaps(company_id: int) -> list:
        rows = session.execute(text("""
            SELECT d.name, g.gap_severity, g.gap_direction,
                   g.gap_description, g.recommendation,
                   g.jobs_signal, g.reviews_sentiment_score
            FROM discourse_reality_gaps g
            JOIN dimensions d ON d.id = g.dimension_id
            WHERE g.company_id = :cid AND g.analysis_version = :v
            ORDER BY g.gap_severity DESC
        """), {"cid": company_id, "v": ANALYSIS_VERSION}).fetchall()
        return [
            {
                "dimensao":      name,
                "severidade":    sev,
                "direcao":       direction,
                "descricao":     desc,
                "recomendacao":  rec,
                "sinal_vagas":   signal,
                "score_reviews": float(score) if score else None,
            }
            for name, sev, direction, desc, rec, signal, score in rows
        ]

    # Vagas por modelo de trabalho
    def get_jobs_summary(company_id: int) -> dict:
        rows = session.execute(text("""
            SELECT work_model, COUNT(*), area
            FROM jobs
            WHERE company_id = :cid
            GROUP BY work_model, area
            ORDER BY COUNT(*) DESC
        """), {"cid": company_id}).fetchall()

        by_model = {}
        by_area  = {}
        total    = 0
        for model, cnt, area in rows:
            by_model[model] = by_model.get(model, 0) + cnt
            by_area[area]   = by_area.get(area, 0)  + cnt
            total           += cnt

        return {
            "total":    total,
            "by_model": {k: round(v / total, 2) for k, v in by_model.items()} if total else {},
            "by_area":  dict(sorted(by_area.items(), key=lambda x: -x[1])[:8]),
        }

    # Linguagem emocional
    def get_emotional_language(company_id: int) -> dict:
        row = session.execute(text("""
            SELECT
                SUM(CASE WHEN tem_linguagem_saudosismo THEN 1 ELSE 0 END),
                SUM(CASE WHEN tem_linguagem_revolta    THEN 1 ELSE 0 END),
                SUM(CASE WHEN tem_linguagem_admiracao  THEN 1 ELSE 0 END),
                COUNT(*)
            FROM reviews
            WHERE company_id = :cid AND is_event_review = false
              AND analysis_version IS NOT NULL
        """), {"cid": company_id}).fetchone()
        saud, rev, adm, total = row
        return {
            "saudosismo": int(saud or 0),
            "revolta":    int(rev  or 0),
            "admiracao":  int(adm  or 0),
            "total":      int(total or 0),
        }

    # Monta contexto completo
    return {
        "c6_bank": {
            "resumo":              get_company_summary(c6_id),
            "dimensoes":           get_dimension_stats(c6_id),
            "temas_emergentes":    get_top_temas(c6_id),
            "eventos":             get_events(c6_id),
            "gaps":                get_gaps(c6_id),
            "vagas":               get_jobs_summary(c6_id),
            "linguagem_emocional": get_emotional_language(c6_id),
        },
        "nubank": {
            "resumo":              get_company_summary(nu_id),
            "dimensoes":           get_dimension_stats(nu_id),
            "temas_emergentes":    get_top_temas(nu_id),
            "eventos":             get_events(nu_id),
            "gaps":                get_gaps(nu_id),
            "vagas":               get_jobs_summary(nu_id),
            "linguagem_emocional": get_emotional_language(nu_id),
        },
    }


# ── Prompt de geração de insights ────────────────────────────────────────────

def build_insights_prompt(context: dict) -> str:
    ctx_str = json.dumps(context, ensure_ascii=False, indent=2)

    return f"""Você recebeu dados consolidados de employer branding do C6 Bank vs Nubank,
baseados em análise de {context['c6_bank']['resumo']['total_reviews']} reviews do C6 Bank
e {context['nubank']['resumo']['total_reviews']} reviews do Nubank no Glassdoor,
cruzadas com dados de vagas do LinkedIn.

DADOS CONSOLIDADOS:
{ctx_str}

Gere entre 10 e 14 insights estratégicos para o C-level do C6 Bank, cobrindo:
1. Oportunidades de captação (onde o C6 pode ganhar talentos que o Nubank está perdendo)
2. Riscos de retenção críticos do C6 (o que está fazendo gente sair)
3. Gaps entre discurso das vagas e realidade vivida
4. Vantagens competitivas reais do C6 vs Nubank
5. Pontos cegos do C6 (problemas não óbvios nos dados)
6. Benchmarks positivos do Nubank que o C6 deveria estudar
7. Plano de ação: 3 ações de alto impacto para implementar nos próximos 90 dias

Para cada insight, retorne um objeto com esta estrutura EXATA:

{{
  "tipo": "oportunidade_captacao" | "risco_retencao" | "gap_discurso_realidade" |
          "vantagem_competitiva" | "ponto_cego" | "benchmark_positivo" | "recomendacao_acao",
  "prioridade": "critica" | "alta" | "media" | "baixa",
  "titulo": "string curta e impactante (máx 80 chars)",
  "headline": "string de 1 frase para slide executivo (máx 120 chars)",
  "descricao": "análise completa em 3-5 frases com dados específicos dos reviews",
  "acao_recomendada": "o que fazer concretamente, em passos específicos",
  "acao_prazo": "30 dias" | "90 dias" | "6 meses" | "1 ano",
  "acao_responsavel": "quem deve liderar (ex: VP de Pessoas, C-Level, Gestores)",
  "impacto_score": número de 1 a 5,
  "esforco_score": número de 1 a 5,
  "supporting_quotes": [
    {{"quote": "trecho literal de uma review", "empresa": "C6 Bank" | "Nubank"}}
  ],
  "dimensoes_relacionadas": ["slug1", "slug2"]
}}

Retorne um JSON com esta estrutura:
{{
  "insights": [ ... array de insights ... ],
  "resumo_executivo": "parágrafo de 4-6 frases para abertura do relatório C-level",
  "top_3_acoes_imediatas": [
    {{"acao": "...", "impacto": "...", "prazo": "..."}}
  ]
}}

IMPORTANTE:
- Use dados ESPECÍFICOS dos reviews (scores, percentuais, quotes literais)
- O RTO do Nubank é uma oportunidade CRÍTICA e concreta para o C6 — explore profundamente
- Liderança e saúde mental têm scores críticos em AMBAS as empresas — quem resolver primeiro ganha
- Seja honesto sobre os problemas graves do C6 (score 1.2 em liderança não é "ponto de melhoria")
- Diversidade é onde o C6 tem vantagem real (5.5 vs 1.9 do Nubank) — comunique isso
- As 90 dias de ações devem ser ESPECÍFICAS, não genéricas"""


# ── Geração e persistência dos insights ──────────────────────────────────────

def generate_and_save_insights(session, context: dict, c6_id: int, nu_id: int,
                                dim_map: dict) -> int:
    prompt = build_insights_prompt(context)

    print(f"\n  🤖 Chamando {MODEL}...")
    print(f"     Contexto: ~{len(prompt) // 4:,} tokens estimados")

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=30000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            result = json.loads(raw)
            break

        except json.JSONDecodeError as e:
            if attempt < 2:
                print(f"  ⚠️  JSON inválido, tentativa {attempt + 1}/3: {e}")
                time.sleep(5)
            else:
                print(f"  ❌ Falha ao parsear JSON após 3 tentativas")
                return 0

        except anthropic.APIError as e:
            if attempt < 2:
                print(f"  ⚠️  API error, tentativa {attempt + 1}/3: {e}")
                time.sleep(10)
            else:
                raise

    insights      = result.get("insights", [])
    resumo_exec   = result.get("resumo_executivo", "")
    top3_acoes    = result.get("top_3_acoes_imediatas", [])

    print(f"  ✅ {len(insights)} insights gerados")
    print(f"\n  📝 RESUMO EXECUTIVO:")
    print(f"  {resumo_exec}\n")

    # Limpa insights existentes desta versão
    session.execute(
        text("DELETE FROM insights WHERE target_company_id = :cid AND analysis_version = :v"),
        {"cid": c6_id, "v": ANALYSIS_VERSION}
    )

    # Mapeia tipo para enum
    TYPE_MAP = {
        "oportunidade_captacao":   "oportunidade_captacao",
        "risco_retencao":          "risco_retencao",
        "gap_discurso_realidade":  "gap_discurso_realidade",
        "vantagem_competitiva":    "vantagem_competitiva",
        "ponto_cego":              "ponto_cego",
        "benchmark_positivo":      "benchmark_positivo",
        "recomendacao_acao":       "recomendacao_acao",
        "tendencia_temporal":      "tendencia_temporal",
    }

    PRIORITY_MAP = {
        "critica": "critica",
        "alta":    "alta",
        "media":   "media",
        "baixa":   "baixa",
    }

    inserted = 0
    for ins in insights:
        tipo      = TYPE_MAP.get(ins.get("tipo", ""), "recomendacao_acao")
        prioridade = PRIORITY_MAP.get(ins.get("prioridade", "media"), "media")
        impacto   = min(max(int(ins.get("impacto_score", 3)), 1), 5)
        esforco   = min(max(int(ins.get("esforco_score", 3)), 1), 5)
        roi       = round(impacto / esforco, 2)

        # Dimensões relacionadas
        dim_slugs = ins.get("dimensoes_relacionadas", [])
        dim_ids   = [
            d_id for d_id, d_slug in dim_map.items()
            if d_slug in dim_slugs
        ]

        # Quotes de evidência
        quotes = ins.get("supporting_quotes", [])

        session.execute(text("""
            INSERT INTO insights (
                target_company_id, compared_company_id, analysis_version,
                insight_type, priority, titulo, headline, descricao,
                acao_recomendada, acao_prazo, acao_responsavel,
                impacto_score, esforco_score, roi_score,
                supporting_quotes, supporting_data, related_dimension_ids,
                is_featured
            ) VALUES (
                :target_company_id, :compared_company_id, :analysis_version,
                :insight_type, :priority, :titulo, :headline, :descricao,
                :acao_recomendada, :acao_prazo, :acao_responsavel,
                :impacto_score, :esforco_score, :roi_score,
                :supporting_quotes, :supporting_data, :related_dimension_ids,
                :is_featured
            )
        """), {
            "target_company_id":  c6_id,
            "compared_company_id": nu_id,
            "analysis_version":   ANALYSIS_VERSION,
            "insight_type":       tipo,
            "priority":           prioridade,
            "titulo":             str(ins.get("titulo", ""))[:300],
            "headline":           str(ins.get("headline", ""))[:200],
            "descricao":          str(ins.get("descricao", "")),
            "acao_recomendada":   str(ins.get("acao_recomendada", "")),
            "acao_prazo":         str(ins.get("acao_prazo", "90 dias"))[:50],
            "acao_responsavel":   str(ins.get("acao_responsavel", ""))[:100],
            "impacto_score":      impacto,
            "esforco_score":      esforco,
            "roi_score":          roi,
            "supporting_quotes":  json.dumps(quotes, ensure_ascii=False),
            "supporting_data":    json.dumps(
                ins.get("supporting_data", {}), ensure_ascii=False
            ),
            "related_dimension_ids": json.dumps(dim_ids),
            "is_featured":        prioridade in ("critica", "alta"),
        })
        inserted += 1

    session.commit()

    # Imprime os insights gerados
    print(f"\n{'=' * 65}")
    print(f"  🎯 INSIGHTS GERADOS — ordenados por ROI")
    print(f"{'=' * 65}")

    priority_order = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    sorted_insights = sorted(
        insights,
        key=lambda x: (priority_order.get(x.get("prioridade", "media"), 2),
                       -x.get("impacto_score", 3))
    )

    for i, ins in enumerate(sorted_insights, 1):
        prioridade = ins.get("prioridade", "media")
        tipo       = ins.get("tipo", "")
        impacto    = ins.get("impacto_score", 3)
        esforco    = ins.get("esforco_score", 3)
        roi        = round(impacto / esforco, 1) if esforco else 0

        icon = {"critica": "🔴", "alta": "🟠", "media": "🟡", "baixa": "🟢"}.get(prioridade, "⚪")
        print(f"\n  {i:2d}. {icon} [{tipo[:25]}] I:{impacto} E:{esforco} ROI:{roi}")
        print(f"      {ins.get('titulo', '')}")
        print(f"      → {ins.get('acao_prazo', '')} | {ins.get('acao_responsavel', '')}")

    if top3_acoes:
        print(f"\n{'=' * 65}")
        print(f"  🚀 TOP 3 AÇÕES IMEDIATAS (próximos 90 dias)")
        print(f"{'=' * 65}")
        for i, acao in enumerate(top3_acoes, 1):
            print(f"\n  {i}. {acao.get('acao', '')}")
            print(f"     Impacto: {acao.get('impacto', '')}")
            print(f"     Prazo:   {acao.get('prazo', '')}")

    return inserted


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Pipeline 07 — Insights Estratégicos (Claude Sonnet)")
    print(f"  Model: {MODEL}  |  Version: {ANALYSIS_VERSION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:

        print("\n  📊 Coletando contexto do banco...")
        context = build_context(session)

        c6_id = session.execute(
            text("SELECT id FROM companies WHERE slug = 'c6_bank'")
        ).scalar()
        nu_id = session.execute(
            text("SELECT id FROM companies WHERE slug = 'nubank'")
        ).scalar()

        dims = session.execute(
            text("SELECT id, slug FROM dimensions WHERE is_active = true")
        ).fetchall()
        dim_map = {id_: slug for id_, slug in dims}

        print(f"  ✅ Contexto montado:")
        print(f"     C6 Bank: {context['c6_bank']['resumo']['total_reviews']} reviews")
        print(f"     Nubank:  {context['nubank']['resumo']['total_reviews']} reviews")
        print(f"     Gaps:    {len(context['c6_bank']['gaps'])} gaps do C6")
        print(f"     Eventos: {len(context['c6_bank']['eventos']) + len(context['nubank']['eventos'])} eventos")

        n = generate_and_save_insights(session, context, c6_id, nu_id, dim_map)

        print(f"\n{'=' * 65}")
        print(f"  ✅ Pipeline macro concluído — {n} insights persistidos")
        print(f"{'=' * 65}")
        print(f"\n🎉 Pipeline completo! Todos os dados estão no banco.")
        print(f"   Próximo passo: conectar o FastAPI ao Next.js")


if __name__ == "__main__":
    main()