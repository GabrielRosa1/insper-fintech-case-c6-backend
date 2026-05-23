#!/usr/bin/env python3
"""
Pipeline Step 07 — Insights Estratégicos via Claude Sonnet (v2)

Idêntico ao 07_insights_macro.py (v1) com três diferenças:
  1. ANALYSIS_VERSION = 'v2' → lê stats v2, salva insights v2
  2. Para C6/Nubank: usa contagem de reviews chronological
  3. INSERT inclui campos da Onda 3: is_active_window, captation_priority,
     empresas_referenciadas

Uso:
    python pipeline/07_insights_macro_v2.py
    python pipeline/07_insights_macro_v2.py --dry-run
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter
from sqlalchemy import text
import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session
from app.config import get_settings

settings = get_settings()
client   = anthropic.Anthropic(api_key=settings.anthropic_api_key)

ANALYSIS_VERSION     = "v2"
MODEL                = "claude-sonnet-4-5"
STRATIFIED_COMPANIES = {"c6_bank", "nubank"}

SYSTEM_PROMPT = """Você é um consultor sênior de employer branding e estratégia de pessoas,
especializado no mercado brasileiro de fintechs, bancos digitais e empresas de tecnologia.

Sua tarefa é analisar dados consolidados de reviews do Glassdoor e vagas do LinkedIn
de múltiplas empresas para gerar insights estratégicos acionáveis para o C-level do C6 Bank,
com foco em captação e retenção de talentos.

Os scores são baseados em reviews CRONOLÓGICAS RECENTES (últimas 300 por empresa para C6/Nubank),
refletindo o estado atual real do mercado.

Os insights devem ser:
- ESPECÍFICOS: baseados nos dados fornecidos, não em generalidades
- ACIONÁVEIS: com recomendações concretas e prazo
- IMPACTANTES: focados no que realmente move o ponteiro de captação e retenção
- HONESTOS: não suavize problemas críticos
- COMPARATIVOS: use o panorama completo do mercado, não só C6 vs Nubank

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


# ── Coleta contexto ───────────────────────────────────────────────────────────

def get_company_summary(session, company_id: int, slug: str) -> dict:
    """Para C6/Nubank conta só chronological — para demais conta tudo."""
    sample_filter = (
        "AND r.sample_type = 'chronological'"
        if slug in STRATIFIED_COMPANIES else ""
    )

    row = session.execute(text(f"""
        SELECT COUNT(*),
               ROUND(AVG(r.avaliacao_geral)::numeric, 2),
               SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END),
               SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END),
               SUM(CASE WHEN r.sentimento_geral = 'misto'    THEN 1 ELSE 0 END)
        FROM reviews r
        WHERE r.company_id = :cid
          AND r.is_event_review = false
          AND r.analysis_version IS NOT NULL
          {sample_filter}
    """), {"cid": company_id}).fetchone()

    total, avg_nota, pos, neg, mix = row
    return {
        "total_reviews": total or 0,
        "avg_nota":      float(avg_nota) if avg_nota else 0,
        "pct_positivo":  round((pos or 0) / total * 100, 1) if total else 0,
        "pct_negativo":  round((neg or 0) / total * 100, 1) if total else 0,
        "pct_misto":     round((mix or 0) / total * 100, 1) if total else 0,
    }


def get_dimension_stats(session, company_id: int, full: bool = True) -> list:
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
        (name, slug, score, mentions, pos, neg, rate, neg_q, pos_q, themes) = row

        entry: dict = {
            "dimensao":      name,
            "slug":          slug,
            "score":         float(score) if score else 0,
            "total_mencoes": mentions or 0,
            "pct_negativo":  round((neg or 0) / mentions * 100, 1) if mentions else 0,
            "pct_positivo":  round((pos or 0) / mentions * 100, 1) if mentions else 0,
        }

        if full:
            entry["taxa_mencao"]    = float(rate) if rate else 0
            entry["top_quotes_neg"] = safe_json_loads(neg_q)[:2]
            entry["top_quotes_pos"] = safe_json_loads(pos_q)[:1]
            entry["top_temas"]      = safe_json_loads(themes)[:3]

        result.append(entry)
    return result


def get_top_temas(session, company_id: int, slug: str, limit: int = 10) -> list:
    sample_filter = (
        "AND r.sample_type = 'chronological'"
        if slug in STRATIFIED_COMPANIES else ""
    )

    rows = session.execute(text(f"""
        SELECT r.temas_emergentes FROM reviews r
        WHERE r.company_id = :cid
          AND r.is_event_review = false
          AND r.temas_emergentes IS NOT NULL
          AND r.analysis_version IS NOT NULL
          {sample_filter}
    """), {"cid": company_id}).fetchall()

    all_temas = []
    for (t,) in rows:
        all_temas.extend(safe_json_loads(t))
    return [{"tema": t, "frequencia": c}
            for t, c in Counter(all_temas).most_common(limit)]


def get_events(session, company_id: int) -> list:
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


def get_gaps(session, company_id: int) -> list:
    rows = session.execute(text("""
        SELECT d.name, g.gap_severity, g.gap_direction,
               g.gap_description, g.recommendation,
               g.jobs_signal, g.reviews_sentiment_score
        FROM discourse_reality_gaps g
        JOIN dimensions d ON d.id = g.dimension_id
        WHERE g.company_id = :cid AND g.analysis_version = 'v1'
        ORDER BY g.gap_severity DESC
    """), {"cid": company_id}).fetchall()
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


def get_jobs_summary(session, company_id: int) -> dict:
    rows = session.execute(text("""
        SELECT work_model, COUNT(*), area
        FROM jobs
        WHERE company_id = :cid
        GROUP BY work_model, area
        ORDER BY COUNT(*) DESC
    """), {"cid": company_id}).fetchall()

    by_model: dict = {}
    by_area:  dict = {}
    total = 0
    for model, cnt, area in rows:
        by_model[model] = by_model.get(model, 0) + cnt
        by_area[area]   = by_area.get(area, 0) + cnt
        total += cnt

    return {
        "total":    total,
        "by_model": {k: round(v / total, 2) for k, v in by_model.items()} if total else {},
        "by_area":  dict(sorted(by_area.items(), key=lambda x: -x[1])[:8]),
    }


def get_emotional_language(session, company_id: int, slug: str) -> dict:
    sample_filter = (
        "AND r.sample_type = 'chronological'"
        if slug in STRATIFIED_COMPANIES else ""
    )

    row = session.execute(text(f"""
        SELECT
            SUM(CASE WHEN r.tem_linguagem_saudosismo THEN 1 ELSE 0 END),
            SUM(CASE WHEN r.tem_linguagem_revolta    THEN 1 ELSE 0 END),
            SUM(CASE WHEN r.tem_linguagem_admiracao  THEN 1 ELSE 0 END),
            COUNT(*)
        FROM reviews r
        WHERE r.company_id = :cid
          AND r.is_event_review = false
          AND r.analysis_version IS NOT NULL
          {sample_filter}
    """), {"cid": company_id}).fetchone()

    saud, rev, adm, total = row
    return {
        "saudosismo": int(saud or 0),
        "revolta":    int(rev  or 0),
        "admiracao":  int(adm  or 0),
        "total":      int(total or 0),
    }


def build_context(session) -> tuple[dict, int, list]:
    companies = session.execute(
        text("SELECT id, slug, name, is_target FROM companies WHERE is_active = true ORDER BY is_target DESC, name")
    ).fetchall()

    c6_id    = None
    comp_ids = []
    context  = {"c6_bank": {}, "concorrentes": {}, "mercado_resumo": {}}

    for company_id, slug, name, is_target in companies:
        summary  = get_company_summary(session, company_id, slug)
        has_data = summary["total_reviews"] > 0

        if is_target:
            c6_id = company_id
            context["c6_bank"] = {
                "nome":                name,
                "resumo":              summary,
                "dimensoes":           get_dimension_stats(session, company_id, full=True),
                "temas_emergentes":    get_top_temas(session, company_id, slug, limit=15),
                "eventos":             get_events(session, company_id),
                "gaps":                get_gaps(session, company_id),
                "vagas":               get_jobs_summary(session, company_id),
                "linguagem_emocional": get_emotional_language(session, company_id, slug),
            }
        else:
            comp_ids.append(company_id)
            comp_context: dict = {"nome": name, "resumo": summary}

            if has_data:
                comp_context["dimensoes"]        = get_dimension_stats(session, company_id, full=False)
                comp_context["temas_emergentes"] = get_top_temas(session, company_id, slug, limit=5)
                comp_context["eventos"]          = get_events(session, company_id)
                comp_context["gaps_criticos"]    = [
                    g for g in get_gaps(session, company_id) if g["severidade"] >= 4
                ]
                comp_context["vagas"]            = get_jobs_summary(session, company_id)
            else:
                comp_context["nota"] = "Sem reviews analisadas — dados de vagas podem estar disponíveis."

            context["concorrentes"][slug] = comp_context

    # Rankings de mercado usando stats v2
    market_rows = session.execute(text("""
        SELECT co.name, co.slug, d.name AS dim_name, d.slug AS dim_slug,
               s.sentiment_score, s.total_mentions
        FROM company_dimension_stats s
        JOIN companies co ON co.id = s.company_id
        JOIN dimensions d  ON d.id  = s.dimension_id
        WHERE s.period = 'all' AND s.analysis_version = :v
          AND s.total_mentions >= 5
        ORDER BY d.display_order, s.sentiment_score DESC
    """), {"v": ANALYSIS_VERSION}).fetchall()

    dim_rankings: dict = {}
    for co_name, co_slug, dim_name, dim_slug, score, mentions in market_rows:
        if dim_slug not in dim_rankings:
            dim_rankings[dim_slug] = {"dimensao": dim_name, "ranking": []}
        dim_rankings[dim_slug]["ranking"].append({
            "empresa": co_name,
            "score":   float(score) if score else 0,
            "mencoes": mentions,
        })

    context["mercado_resumo"]["rankings_por_dimensao"] = list(dim_rankings.values())
    return context, c6_id, comp_ids


def build_insights_prompt(context: dict) -> str:
    c6_reviews = context["c6_bank"]["resumo"]["total_reviews"]
    comp_names = [v["nome"] for v in context["concorrentes"].values()]
    comp_str   = ", ".join(comp_names)
    ctx_str    = json.dumps(context, ensure_ascii=False, indent=2)

    return f"""Você recebeu dados consolidados de employer branding do C6 Bank comparado
com todo o mercado: {comp_str}.

IMPORTANTE: os scores do C6 Bank e Nubank são baseados em reviews CRONOLÓGICAS RECENTES
(últimas 300 cada), refletindo a realidade atual — não amostragem estratificada.

Base de dados:
- C6 Bank: {c6_reviews} reviews cronológicas recentes analisadas
- Concorrentes: dados variados por empresa (ver contexto)

DADOS CONSOLIDADOS:
{ctx_str}

Gere entre 12 e 16 insights estratégicos para o C-level do C6 Bank.
Para cada insight, retorne um objeto com esta estrutura EXATA:

{{
  "tipo": "oportunidade_captacao" | "risco_retencao" | "gap_discurso_realidade" |
          "vantagem_competitiva" | "ponto_cego" | "benchmark_positivo" |
          "recomendacao_acao" | "tendencia_temporal",
  "prioridade": "critica" | "alta" | "media" | "baixa",
  "titulo": "string curta e impactante (máx 80 chars)",
  "headline": "string de 1 frase para slide executivo (máx 120 chars)",
  "descricao": "análise completa em 3-5 frases com dados específicos",
  "acao_recomendada": "o que fazer concretamente, em passos específicos",
  "acao_prazo": "30 dias" | "90 dias" | "6 meses" | "1 ano",
  "acao_responsavel": "quem deve liderar",
  "empresas_referenciadas": ["C6 Bank", "Nubank", ...],
  "impacto_score": 1-5,
  "esforco_score": 1-5,
  "supporting_quotes": [{{"quote": "trecho literal", "empresa": "nome"}}],
  "dimensoes_relacionadas": ["slug1", "slug2"],
  "is_active_window": true (SOMENTE para oportunidade_captacao) | false,
  "captation_priority": 1-5 (SOMENTE quando is_active_window = true) | null
}}

Retorne um JSON com esta estrutura:
{{
  "insights": [...],
  "resumo_executivo": "4-6 frases para abertura do relatório C-level",
  "top_3_acoes_imediatas": [{{"acao": "...", "impacto": "...", "prazo": "..."}}],
  "panorama_mercado": "2-3 frases sobre o estado do employer branding no setor"
}}

REGRAS:
- Use dados ESPECÍFICOS com scores, percentuais, quotes
- Compare C6 com TODO o mercado, não só com Nubank
- Seja honesto — scores críticos não são "pontos de melhoria"
- Identifique problemas exclusivos do C6 vs endêmicos do setor
- is_active_window = true SOMENTE para tipo oportunidade_captacao"""


def generate_and_save_insights(
    session, context: dict, c6_id: int,
    comp_ids: list, dim_map: dict,
    dry_run: bool = False
) -> int:
    prompt = build_insights_prompt(context)

    print(f"\n  🤖 Chamando {MODEL}...")
    print(f"     Contexto: ~{len(prompt) // 4:,} tokens estimados")
    print(f"     Empresas: C6 Bank + {len(context['concorrentes'])} concorrentes")

    result = None
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
                print(f"  ⚠️  JSON inválido, tentativa {attempt+1}/3: {e}")
                time.sleep(5)
            else:
                print(f"  ❌ Falha ao parsear JSON após 3 tentativas")
                return 0

        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"  ⏳ Rate limit — aguardando {wait}s...")
            time.sleep(wait)

        except anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 529):
                wait = 30 * (attempt + 1)
                print(f"  ⏳ API status {e.status_code} — aguardando {wait}s...")
                time.sleep(wait)
            else:
                print(f"  ❌ API status {e.status_code}: {e}")
                return 0

        except anthropic.APIError as e:
            if attempt < 2:
                print(f"  ⚠️  API error, tentativa {attempt+1}/3: {e}")
                time.sleep(10)
            else:
                raise

    if not result:
        return 0

    insights         = result.get("insights", [])
    resumo_exec      = result.get("resumo_executivo", "")
    top3_acoes       = result.get("top_3_acoes_imediatas", [])
    panorama_mercado = result.get("panorama_mercado", "")

    print(f"  ✅ {len(insights)} insights gerados")
    if panorama_mercado:
        print(f"\n  🌐 PANORAMA: {panorama_mercado}\n")
    print(f"  📝 RESUMO EXECUTIVO:\n  {resumo_exec}\n")

    if dry_run:
        print(f"\n  [DRY RUN] Nenhum insight salvo no banco.")
        _print_insights_preview(insights)
        return len(insights)

    # Limpa insights v2 existentes para o C6
    session.execute(
        text("DELETE FROM insights WHERE target_company_id = :cid AND analysis_version = :v"),
        {"cid": c6_id, "v": ANALYSIS_VERSION}
    )

    TYPE_MAP = {
        "oportunidade_captacao":  "oportunidade_captacao",
        "risco_retencao":         "risco_retencao",
        "gap_discurso_realidade": "gap_discurso_realidade",
        "vantagem_competitiva":   "vantagem_competitiva",
        "ponto_cego":             "ponto_cego",
        "benchmark_positivo":     "benchmark_positivo",
        "recomendacao_acao":      "recomendacao_acao",
        "tendencia_temporal":     "tendencia_temporal",
    }
    PRIORITY_MAP = {"critica": "critica", "alta": "alta", "media": "media", "baixa": "baixa"}

    inserted = 0
    for ins in insights:
        tipo       = TYPE_MAP.get(ins.get("tipo", ""), "recomendacao_acao")
        prioridade = PRIORITY_MAP.get(ins.get("prioridade", "media"), "media")
        impacto    = min(max(int(ins.get("impacto_score", 3)), 1), 5)
        esforco    = min(max(int(ins.get("esforco_score", 3)), 1), 5)
        roi        = round(impacto / esforco, 2)

        dim_slugs = ins.get("dimensoes_relacionadas", [])
        dim_ids   = [d_id for d_id, d_slug in dim_map.items() if d_slug in dim_slugs]

        compared_id = None
        for emp_name in ins.get("empresas_referenciadas", []):
            row = session.execute(
                text("SELECT id FROM companies WHERE name = :name"),
                {"name": emp_name}
            ).fetchone()
            if row and row[0] != c6_id:
                compared_id = row[0]
                break

        # Campos novos da Onda 3
        is_active_window = bool(ins.get("is_active_window", False))
        captation_priority = ins.get("captation_priority") if is_active_window else None

        session.execute(text("""
            INSERT INTO insights (
                target_company_id, compared_company_id, analysis_version,
                insight_type, priority, titulo, headline, descricao,
                acao_recomendada, acao_prazo, acao_responsavel,
                impacto_score, esforco_score, roi_score,
                supporting_quotes, supporting_data, related_dimension_ids,
                empresas_referenciadas, is_featured,
                is_active_window, captation_priority
            ) VALUES (
                :target_company_id, :compared_company_id, :analysis_version,
                :insight_type, :priority, :titulo, :headline, :descricao,
                :acao_recomendada, :acao_prazo, :acao_responsavel,
                :impacto_score, :esforco_score, :roi_score,
                :supporting_quotes, :supporting_data, :related_dimension_ids,
                :empresas_referenciadas, :is_featured,
                :is_active_window, :captation_priority
            )
        """), {
            "target_company_id":    c6_id,
            "compared_company_id":  compared_id,
            "analysis_version":     ANALYSIS_VERSION,
            "insight_type":         tipo,
            "priority":             prioridade,
            "titulo":               str(ins.get("titulo", ""))[:300],
            "headline":             str(ins.get("headline", ""))[:200],
            "descricao":            str(ins.get("descricao", "")),
            "acao_recomendada":     str(ins.get("acao_recomendada", "")),
            "acao_prazo":           str(ins.get("acao_prazo", "90 dias"))[:50],
            "acao_responsavel":     str(ins.get("acao_responsavel", ""))[:100],
            "impacto_score":        impacto,
            "esforco_score":        esforco,
            "roi_score":            roi,
            "supporting_quotes":    json.dumps(ins.get("supporting_quotes", []), ensure_ascii=False),
            "supporting_data":      json.dumps(ins.get("supporting_data", {}), ensure_ascii=False),
            "related_dimension_ids": json.dumps(dim_ids),
            "empresas_referenciadas": json.dumps(ins.get("empresas_referenciadas", []), ensure_ascii=False),
            "is_featured":          prioridade in ("critica", "alta"),
            "is_active_window":     is_active_window,
            "captation_priority":   captation_priority,
        })
        inserted += 1

    session.commit()
    _print_insights_preview(insights)
    return inserted


def _print_insights_preview(insights: list):
    print(f"\n{'=' * 65}")
    print(f"  🎯 INSIGHTS — ordenados por prioridade e ROI")
    print(f"{'=' * 65}")

    priority_order = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    sorted_insights = sorted(
        insights,
        key=lambda x: (priority_order.get(x.get("prioridade", "media"), 2),
                       -x.get("impacto_score", 3))
    )

    for i, ins in enumerate(sorted_insights, 1):
        prioridade = ins.get("prioridade", "media")
        impacto    = ins.get("impacto_score", 3)
        esforco    = ins.get("esforco_score", 3)
        roi        = round(impacto / esforco, 1) if esforco else 0
        empresas   = ", ".join(ins.get("empresas_referenciadas", []))
        window_tag = " 🔓" if ins.get("is_active_window") else ""

        icon = {"critica": "🔴", "alta": "🟠", "media": "🟡", "baixa": "🟢"}.get(prioridade, "⚪")
        print(f"\n  {i:2d}. {icon} [{ins.get('tipo','')[:22]}]{window_tag}  I:{impacto} E:{esforco} ROI:{roi}")
        print(f"      {ins.get('titulo', '')}")
        if empresas:
            print(f"      🏢 {empresas}")
        print(f"      → {ins.get('acao_prazo', '')} | {ins.get('acao_responsavel', '')}")


def main():
    parser = argparse.ArgumentParser(description="Insights macro v2")
    parser.add_argument("--dry-run", action="store_true",
                        help="Gera insights mas não persiste no banco.")
    args = parser.parse_args()

    print("=" * 65)
    print("  Pipeline 07 — Insights Estratégicos (v2)")
    print(f"  Model: {MODEL}  |  Version: {ANALYSIS_VERSION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:
        print("\n  📊 Coletando contexto do banco (stats v2)...")
        context, c6_id, comp_ids = build_context(session)

        if not c6_id:
            print("  ❌ C6 Bank não encontrado. Abortando.")
            return

        dims    = session.execute(text("SELECT id, slug FROM dimensions WHERE is_active = true")).fetchall()
        dim_map = {id_: slug for id_, slug in dims}

        print(f"  ✅ Contexto montado:")
        print(f"     C6 Bank (target): {context['c6_bank']['resumo']['total_reviews']} reviews chronological")
        for slug, data in context["concorrentes"].items():
            total = data.get("resumo", {}).get("total_reviews", 0)
            print(f"     {slug:<20} {total} reviews")
        print(f"     Rankings v2: {len(context['mercado_resumo'].get('rankings_por_dimensao', []))} dimensões")

        n = generate_and_save_insights(
            session, context, c6_id, comp_ids, dim_map,
            dry_run=args.dry_run
        )

        prefix = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{'=' * 65}")
        print(f"  ✅ {prefix}{n} insights {'simulados' if args.dry_run else 'persistidos'} (v2)")
        print(f"{'=' * 65}")
        if not args.dry_run:
            print(f"\n🚀 Próximo passo: python pipeline/08_embeddings.py")


if __name__ == "__main__":
    main()