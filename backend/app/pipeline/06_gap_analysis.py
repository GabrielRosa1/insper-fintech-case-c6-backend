#!/usr/bin/env python3
"""
Pipeline Step 06 — Análise de Gap: Discurso vs Realidade

Cruza o que as vagas prometem (LinkedIn) com o que os
funcionários vivem (Glassdoor reviews).

Gaps identificados:
  1. Modelo de trabalho: vagas on-site vs queixas de presencial
  2. Stack técnica: skills mais demandadas vs percepção nas reviews
  3. Cultura: palavras-chave das vagas vs sentimento real
  4. Senioridade: nível exigido vs percepção de crescimento
  5. Skills gap: o que as vagas pedem que não existe na realidade

Persiste em discourse_reality_gaps com severity 1-5.

Uso:
    cd backend/
    python -m app.pipeline.06_gap_analysis
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from collections import Counter
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session
from app.config import get_settings

settings = get_settings()
ANALYSIS_VERSION = settings.analysis_version

# Skills técnicas agrupadas por categoria
TECH_CATEGORIES = {
    "ml_ai":     ["python", "machine_learning", "deep_learning", "nlp",
                  "tensorflow", "pytorch", "scikit_learn"],
    "cloud":     ["aws", "gcp", "azure"],
    "data_eng":  ["spark", "kafka", "airflow", "dbt", "databricks",
                  "bigquery", "sql", "pandas"],
    "backend":   ["java", "golang", "kotlin", "scala", "c#",
                  "api_rest", "microservices", "docker", "kubernetes"],
    "frontend":  ["javascript", "typescript"],
    "devops":    ["terraform", "ci_cd", "git"],
}


def safe_json_loads(val) -> list:
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return []


def safe_json_dumps(obj) -> str:
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)


# ── Análise de modelo de trabalho ─────────────────────────────────────────────

def analyze_work_model_gap(session, company_id: int, dim_map: dict) -> dict | None:
    """
    Gap: vagas prometem X modelo de trabalho, reviews reclamam de Y.
    """
    # Distribuição de vagas por modelo
    jobs = session.execute(text("""
        SELECT work_model, COUNT(*) as cnt
        FROM jobs
        WHERE company_id = :cid
        GROUP BY work_model
    """), {"cid": company_id}).fetchall()

    if not jobs:
        return None

    total_jobs = sum(r[1] for r in jobs)
    job_models = {r[0]: r[1] / total_jobs for r in jobs}

    pct_on_site = job_models.get("on_site", 0)
    pct_hybrid  = job_models.get("hybrid", 0)
    pct_remote  = job_models.get("remote", 0)

    # Sentimento na dimensão modelo_trabalho
    dim_id = dim_map.get("modelo_trabalho")
    if not dim_id:
        return None

    stats = session.execute(text("""
        SELECT sentiment_score, total_mentions, negative_count, top_negative_quotes
        FROM company_dimension_stats
        WHERE company_id = :cid AND dimension_id = :did
          AND period = 'all' AND analysis_version = :v
    """), {"cid": company_id, "did": dim_id, "v": ANALYSIS_VERSION}).fetchone()

    if not stats:
        return None

    score, mentions, neg_count, neg_quotes_raw = stats
    pct_neg = round(neg_count / mentions, 3) if mentions else 0
    neg_quotes = safe_json_loads(neg_quotes_raw)

    # Determina direção e severidade do gap
    if pct_on_site >= 0.8 and score <= 3.0:
        direction  = "promise_better"
        severity   = 5
        description = (
            f"{pct_on_site:.0%} das vagas exigem presencial, "
            f"mas modelo de trabalho tem score {score:.1f}/10 nas reviews. "
            f"{pct_neg:.0%} das menções são negativas. "
            "Candidatos qualificados descartam a empresa antes de entrevistar."
        )
        recommendation = (
            "Implementar modelo híbrido estruturado com pelo menos 2 dias remotos/semana. "
            "No curto prazo, comunicar claramente nas vagas os benefícios do presencial "
            "(localização, infraestrutura, cultura). "
            "Monitorar impacto no funil de recrutamento."
        )
    elif pct_hybrid >= 0.5 and score <= 4.0:
        direction  = "promise_better"
        severity   = 4
        description = (
            f"{pct_hybrid:.0%} das vagas prometem híbrido, "
            f"mas reviews avaliam modelo de trabalho com score {score:.1f}/10. "
            "Existe gap entre a promessa do processo seletivo e a experiência real."
        )
        recommendation = (
            "Revisar política de híbrido para garantir que a flexibilidade prometida "
            "nas vagas seja realmente vivida pelos funcionários. "
            "Coletar NPS interno sobre modelo de trabalho."
        )
    elif score >= 7.0:
        direction  = "reality_better"
        severity   = 1
        description = (
            f"Modelo de trabalho bem avaliado (score {score:.1f}/10). "
            "Alinhamento entre o que é prometido e o que é entregue."
        )
        recommendation = "Manter política atual e destacar nas vagas como diferencial."
    else:
        direction  = "aligned"
        severity   = 2
        description = f"Modelo de trabalho com score médio {score:.1f}/10. Sem gap crítico."
        recommendation = "Monitorar evolução do sentimento."

    supporting_reviews = session.execute(text("""
        SELECT rd.review_id FROM review_dimensions rd
        JOIN reviews r ON r.id = rd.review_id
        WHERE r.company_id = :cid AND rd.dimension_id = :did
          AND rd.sentiment = 'negativo' AND rd.analysis_version = :v
        ORDER BY rd.intensity DESC
        LIMIT 5
    """), {"cid": company_id, "did": dim_id, "v": ANALYSIS_VERSION}).fetchall()

    return {
        "dimension_slug":           "modelo_trabalho",
        "jobs_signal":              f"{pct_on_site:.0%} on-site | {pct_hybrid:.0%} híbrido | {pct_remote:.0%} remoto",
        "jobs_pct_mentioning":      pct_on_site + pct_hybrid,
        "reviews_sentiment_score":  score,
        "reviews_pct_negative":     pct_neg,
        "gap_direction":            direction,
        "gap_severity":             severity,
        "gap_description":          description,
        "supporting_job_examples":  safe_json_dumps([]),
        "supporting_review_ids":    safe_json_dumps([r[0] for r in supporting_reviews]),
        "recommendation":           recommendation,
    }


# ── Análise de skills gap ─────────────────────────────────────────────────────

def analyze_skills_gap(session, company_id: int, company_name: str) -> list[dict]:
    """
    Identifica skills muito demandadas nas vagas que não aparecem
    como pontos fortes nas reviews de tech.
    """
    # Skills mais demandadas nas vagas desta empresa
    skill_rows = session.execute(text("""
        SELECT js.skill, COUNT(*) as cnt
        FROM job_skills js
        JOIN jobs j ON j.id = js.job_id
        WHERE j.company_id = :cid
        GROUP BY js.skill
        ORDER BY cnt DESC
    """), {"cid": company_id}).fetchall()

    if not skill_rows:
        return []

    total_jobs = session.execute(text(
        "SELECT COUNT(*) FROM jobs WHERE company_id = :cid"
    ), {"cid": company_id}).scalar() or 1

    # Skills com alta demanda (>20% das vagas)
    high_demand = {
        row[0]: round(row[1] / total_jobs, 3)
        for row in skill_rows
        if row[1] / total_jobs >= 0.10
    }

    # Verifica menção positiva dessas skills nas reviews (via temas emergentes)
    review_temas = session.execute(text("""
        SELECT temas_emergentes FROM reviews
        WHERE company_id = :cid
          AND temas_emergentes IS NOT NULL
          AND is_event_review = false
          AND analysis_version IS NOT NULL
    """), {"cid": company_id}).fetchall()

    all_temas_text = " ".join([
        str(t).lower()
        for row in review_temas
        for t in safe_json_loads(row[0])
    ])

    # Stack técnica nas reviews
    tech_reviews = session.execute(text("""
        SELECT rd.sentiment, rd.evidence_quote
        FROM review_dimensions rd
        JOIN reviews r ON r.id = rd.review_id
        JOIN dimensions d ON d.id = rd.dimension_id
        WHERE r.company_id = :cid AND d.slug = 'tech_stack'
          AND rd.analysis_version = :v
        ORDER BY rd.intensity DESC
        LIMIT 20
    """), {"cid": company_id, "v": ANALYSIS_VERSION}).fetchall()

    tech_neg_quotes = [r[1] for r in tech_reviews if r[0] == "negativo" and r[1]]
    tech_pos_quotes = [r[1] for r in tech_reviews if r[0] == "positivo" and r[1]]

    gaps = []

    # Gap: skills muito demandadas sem menção positiva nas reviews
    for skill, pct in sorted(high_demand.items(), key=lambda x: -x[1])[:10]:
        mentioned_positively = skill.lower() in all_temas_text

        if not mentioned_positively and pct >= 0.15:
            gaps.append({
                "dimension_slug":           "tech_stack",
                "jobs_signal":              f"Skill '{skill}' em {pct:.0%} das vagas",
                "jobs_pct_mentioning":      pct,
                "reviews_sentiment_score":  None,
                "reviews_pct_negative":     None,
                "gap_direction":            "promise_better",
                "gap_severity":             3 if pct >= 0.25 else 2,
                "gap_description":          (
                    f"A skill '{skill}' aparece em {pct:.0%} das vagas do {company_name}, "
                    f"mas não é mencionada positivamente nas reviews. "
                    "Possível gap de treinamento ou expectativa não alinhada."
                ),
                "supporting_job_examples":  safe_json_dumps([]),
                "supporting_review_ids":    safe_json_dumps([]),
                "recommendation":           (
                    f"Verificar se candidatos contratados para roles com '{skill}' "
                    f"têm suporte técnico adequado. "
                    "Considerar programa de upskilling interno."
                ),
            })

    return gaps


# ── Análise de liderança: promessa vs realidade ───────────────────────────────

def analyze_leadership_gap(session, company_id: int, dim_map: dict) -> dict | None:
    """
    Liderança é o maior driver de saída — qual o gap de comunicação externo?
    """
    dim_id = dim_map.get("lideranca")
    if not dim_id:
        return None

    stats = session.execute(text("""
        SELECT sentiment_score, total_mentions, negative_count,
               positive_count, top_negative_quotes
        FROM company_dimension_stats
        WHERE company_id = :cid AND dimension_id = :did
          AND period = 'all' AND analysis_version = :v
    """), {"cid": company_id, "did": dim_id, "v": ANALYSIS_VERSION}).fetchone()

    if not stats:
        return None

    score, mentions, neg_count, pos_count, neg_quotes_raw = stats
    pct_neg = round(neg_count / mentions, 3) if mentions else 0

    # Vagas que mencionam liderança/gestão (títulos de manager, lead, etc.)
    mgmt_jobs = session.execute(text("""
        SELECT COUNT(*) FROM jobs
        WHERE company_id = :cid
          AND (LOWER(titulo) LIKE '%manager%'
           OR LOWER(titulo) LIKE '%gerente%'
           OR LOWER(titulo) LIKE '%lead%'
           OR LOWER(titulo) LIKE '%lider%'
           OR LOWER(titulo) LIKE '%head%')
    """), {"cid": company_id}).scalar() or 0

    total_jobs = session.execute(text(
        "SELECT COUNT(*) FROM jobs WHERE company_id = :cid"
    ), {"cid": company_id}).scalar() or 1

    pct_mgmt_jobs = round(mgmt_jobs / total_jobs, 3)

    neg_quotes = safe_json_loads(neg_quotes_raw)

    if score <= 2.0 and pct_neg >= 0.6:
        severity = 5
        description = (
            f"Liderança é o maior problema identificado: score {score:.1f}/10, "
            f"{pct_neg:.0%} de menções negativas em {mentions} reviews. "
            f"{pct_mgmt_jobs:.0%} das vagas abertas são para posições de liderança — "
            "contratar mais líderes sem resolver a cultura de gestão vai amplificar o problema."
        )
        recommendation = (
            "PRIORIDADE MÁXIMA: Implementar programa de desenvolvimento de lideranças "
            "antes de qualquer nova contratação para cargos de gestão. "
            "Criar ciclos de feedback 360° obrigatórios para gestores. "
            "Considerar avaliação de desempenho dos gestores pelos liderados "
            "como critério de promoção e retenção."
        )
    elif score <= 4.0:
        severity = 4
        description = (
            f"Liderança com score baixo: {score:.1f}/10, {pct_neg:.0%} negativo. "
            "Impacto direto na retenção e na capacidade de atrair talentos sêniores."
        )
        recommendation = (
            "Investir em treinamento de gestores com foco em feedback, "
            "transparência e gestão de pessoas. "
            "Mapear líderes específicos com maior índice de reclamações."
        )
    else:
        severity = 2
        description = f"Liderança com score médio {score:.1f}/10."
        recommendation = "Monitorar e investir em desenvolvimento contínuo de líderes."

    supporting_reviews = session.execute(text("""
        SELECT rd.review_id FROM review_dimensions rd
        JOIN reviews r ON r.id = rd.review_id
        WHERE r.company_id = :cid AND rd.dimension_id = :did
          AND rd.sentiment = 'negativo' AND rd.analysis_version = :v
        ORDER BY rd.intensity DESC
        LIMIT 5
    """), {"cid": company_id, "did": dim_id, "v": ANALYSIS_VERSION}).fetchall()

    return {
        "dimension_slug":           "lideranca",
        "jobs_signal":              f"{pct_mgmt_jobs:.0%} das vagas são para liderança",
        "jobs_pct_mentioning":      pct_mgmt_jobs,
        "reviews_sentiment_score":  score,
        "reviews_pct_negative":     pct_neg,
        "gap_direction":            "promise_better",
        "gap_severity":             severity,
        "gap_description":          description,
        "supporting_job_examples":  safe_json_dumps([]),
        "supporting_review_ids":    safe_json_dumps([r[0] for r in supporting_reviews]),
        "recommendation":           recommendation,
    }


# ── Análise de saúde mental ───────────────────────────────────────────────────

def analyze_health_gap(session, company_id: int, dim_map: dict) -> dict | None:
    """
    Burnout e saúde mental raramente aparecem nas vagas mas dominam reviews negativas.
    """
    dim_id = dim_map.get("saude_mental")
    if not dim_id:
        return None

    stats = session.execute(text("""
        SELECT sentiment_score, total_mentions, negative_count, top_negative_quotes
        FROM company_dimension_stats
        WHERE company_id = :cid AND dimension_id = :did
          AND period = 'all' AND analysis_version = :v
    """), {"cid": company_id, "did": dim_id, "v": ANALYSIS_VERSION}).fetchone()

    if not stats:
        return None

    score, mentions, neg_count, neg_quotes_raw = stats
    pct_neg = round(neg_count / mentions, 3) if mentions else 0

    if score <= 2.0:
        severity = 5
        description = (
            f"Saúde mental e WLB: score crítico de {score:.1f}/10 em {mentions} menções. "
            f"{pct_neg:.0%} negativo. "
            "Burnout e pressão excessiva são mencionados como razão de saída. "
            "Este tema não aparece nas vagas mas é determinante na decisão de aceitar/recusar ofertas."
        )
        recommendation = (
            "Implementar políticas concretas de WLB: limites de reuniões, "
            "direito à desconexão, metas realistas. "
            "Treinar gestores para identificar sinais de burnout. "
            "Comunicar ativamente os benefícios de saúde mental nas vagas — "
            "é um diferencial competitivo real frente ao mercado atual."
        )
    else:
        severity = 3
        description = f"Saúde mental com score {score:.1f}/10. Monitoramento recomendado."
        recommendation = "Manter programas de bem-estar e monitorar evolução."

    return {
        "dimension_slug":           "saude_mental",
        "jobs_signal":              "Raramente mencionado nas vagas",
        "jobs_pct_mentioning":      0.0,
        "reviews_sentiment_score":  score,
        "reviews_pct_negative":     pct_neg,
        "gap_direction":            "promise_better",
        "gap_severity":             severity,
        "gap_description":          description,
        "supporting_job_examples":  safe_json_dumps([]),
        "supporting_review_ids":    safe_json_dumps([]),
        "recommendation":           recommendation,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Pipeline 06 — Gap Analysis: Discurso vs Realidade")
    print(f"  Version: {ANALYSIS_VERSION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:

        # Limpa gaps existentes desta versão
        session.execute(
            text("DELETE FROM discourse_reality_gaps WHERE analysis_version = :v"),
            {"v": ANALYSIS_VERSION}
        )
        session.commit()

        # Carrega dimensões
        dims = session.execute(
            text("SELECT id, slug FROM dimensions WHERE is_active = true")
        ).fetchall()
        dim_map = {slug: id_ for id_, slug in dims}

        companies = session.execute(
            text("SELECT id, name, slug FROM companies WHERE is_active = true ORDER BY is_target DESC")
        ).fetchall()

        total_gaps = 0

        for company_id, company_name, slug in companies:
            print(f"\n  🏢 {company_name}")

            gaps_to_insert = []

            # 1. Gap de modelo de trabalho
            wm_gap = analyze_work_model_gap(session, company_id, dim_map)
            if wm_gap:
                gaps_to_insert.append(wm_gap)
                sev = wm_gap["gap_severity"]
                icon = "🔴" if sev >= 4 else "⚠️ " if sev >= 3 else "✅"
                print(f"    {icon} Modelo de trabalho — severidade {sev}/5")
                print(f"       {wm_gap['jobs_signal']}")
                print(f"       Reviews score: {wm_gap['reviews_sentiment_score']:.1f}/10")

            # 2. Gap de liderança
            lead_gap = analyze_leadership_gap(session, company_id, dim_map)
            if lead_gap:
                gaps_to_insert.append(lead_gap)
                sev = lead_gap["gap_severity"]
                icon = "🔴" if sev >= 4 else "⚠️ " if sev >= 3 else "✅"
                print(f"    {icon} Liderança — severidade {sev}/5")
                print(f"       Reviews score: {lead_gap['reviews_sentiment_score']:.1f}/10 | "
                      f"{lead_gap['reviews_pct_negative']:.0%} negativo")

            # 3. Gap de saúde mental
            health_gap = analyze_health_gap(session, company_id, dim_map)
            if health_gap:
                gaps_to_insert.append(health_gap)
                sev = health_gap["gap_severity"]
                icon = "🔴" if sev >= 4 else "⚠️ " if sev >= 3 else "✅"
                print(f"    {icon} Saúde Mental — severidade {sev}/5")
                print(f"       Reviews score: {health_gap['reviews_sentiment_score']:.1f}/10")

            # 4. Skills gaps técnicos
            skill_gaps = analyze_skills_gap(session, company_id, company_name)
            if skill_gaps:
                print(f"    ⚠️  {len(skill_gaps)} skills gaps técnicos identificados")
                for sg in skill_gaps[:3]:
                    print(f"       • {sg['jobs_signal']}")
                gaps_to_insert.extend(skill_gaps)

            # Persiste todos os gaps desta empresa
            for gap in gaps_to_insert:
                dim_id = dim_map.get(gap["dimension_slug"])
                if not dim_id:
                    continue

                session.execute(text("""
                    INSERT INTO discourse_reality_gaps (
                        company_id, dimension_id, analysis_version,
                        jobs_signal, jobs_pct_mentioning,
                        reviews_sentiment_score, reviews_pct_negative,
                        gap_direction, gap_severity, gap_description,
                        supporting_job_examples, supporting_review_ids,
                        recommendation
                    ) VALUES (
                        :company_id, :dimension_id, :analysis_version,
                        :jobs_signal, :jobs_pct_mentioning,
                        :reviews_sentiment_score, :reviews_pct_negative,
                        :gap_direction, :gap_severity, :gap_description,
                        :supporting_job_examples, :supporting_review_ids,
                        :recommendation
                    )
                """), {
                    "company_id":               company_id,
                    "dimension_id":             dim_id,
                    "analysis_version":         ANALYSIS_VERSION,
                    "jobs_signal":              gap["jobs_signal"],
                    "jobs_pct_mentioning":      gap["jobs_pct_mentioning"],
                    "reviews_sentiment_score":  gap["reviews_sentiment_score"],
                    "reviews_pct_negative":     gap["reviews_pct_negative"],
                    "gap_direction":            gap["gap_direction"],
                    "gap_severity":             gap["gap_severity"],
                    "gap_description":          gap["gap_description"],
                    "supporting_job_examples":  gap["supporting_job_examples"],
                    "supporting_review_ids":    gap["supporting_review_ids"],
                    "recommendation":           gap["recommendation"],
                })

            session.commit()
            total_gaps += len(gaps_to_insert)
            print(f"    ✅ {len(gaps_to_insert)} gaps persistidos")

        # Resumo final
        print(f"\n{'=' * 65}")
        print(f"  📊 RESUMO DE GAPS — C6 Bank (TARGET)")
        print(f"{'=' * 65}")

        c6_id = session.execute(
            text("SELECT id FROM companies WHERE slug = 'c6_bank'")
        ).scalar()

        gaps = session.execute(text("""
            SELECT d.name, g.gap_severity, g.gap_direction,
                   g.gap_description, g.recommendation
            FROM discourse_reality_gaps g
            JOIN dimensions d ON d.id = g.dimension_id
            WHERE g.company_id = :cid AND g.analysis_version = :v
            ORDER BY g.gap_severity DESC
        """), {"cid": c6_id, "v": ANALYSIS_VERSION}).fetchall()

        for dim_name, severity, direction, description, recommendation in gaps:
            icon = "🔴" if severity >= 4 else "⚠️ " if severity >= 3 else "✅"
            print(f"\n  {icon} {dim_name} — Severidade {severity}/5")
            print(f"     {description[:120]}...")
            print(f"     💡 {recommendation[:100]}...")

        print(f"\n{'=' * 65}")
        print(f"  ✅ {total_gaps} gaps analisados e persistidos")
        print(f"{'=' * 65}")
        print(f"\n🚀 Próximo passo: python -m app.pipeline.07_insights_macro")


if __name__ == "__main__":
    main()