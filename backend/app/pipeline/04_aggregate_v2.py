#!/usr/bin/env python3
"""
Pipeline Step 04 — Agregações estratégicas (v2)

Idêntico ao 04_aggregate.py (v1) com duas diferenças:
  1. ANALYSIS_VERSION = 'v2'
  2. Para C6 Bank e Nubank: usa SOMENTE reviews com sample_type = 'chronological'
     (as 300 novas reviews cronológicas de cada empresa)
  3. Outras 5 empresas: usa todas as reviews (já eram cronológicas)

Isso corrige o viés da amostragem estratificada original.

Uso:
    python pipeline/04_aggregate_v2.py
    python pipeline/04_aggregate_v2.py --dry-run
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter
from sqlalchemy import text
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session
from app.config import get_settings

settings = get_settings()

ANALYSIS_VERSION     = "v2"
STRATIFIED_COMPANIES = {"c6_bank", "nubank"}


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


def calc_sentiment_score(pos: int, mix: int, neu: int, neg: int) -> float:
    total = pos + mix + neu + neg
    if total == 0:
        return 5.0
    raw = (pos * 1.0 + mix * 0.5 + neu * 0.5 + neg * 0.0) / total
    return round(raw * 10, 2)


def aggregate_dimension_stats(session, dry_run: bool = False) -> int:
    print("\n  📊 Calculando stats por empresa × dimensão × período (v2)...")
    print(f"     Filtro C6/Nubank: somente sample_type = 'chronological'")

    if not dry_run:
        session.execute(
            text("DELETE FROM company_dimension_stats WHERE analysis_version = :v"),
            {"v": ANALYSIS_VERSION}
        )
        session.commit()

    slugs_list = list(STRATIFIED_COMPANIES)

    # ── Carrega review_dimensions com filtro de sample_type ──────────────────
    # Para empresas estratificadas → só chronological
    # Para as demais → todas (já eram cronológicas)
    rows = session.execute(text("""
        SELECT
            r.company_id,
            r.data_review,
            r.avaliacao_geral,
            rd.dimension_id,
            rd.sentiment,
            rd.intensity,
            rd.evidence_quote,
            r.temas_emergentes
        FROM review_dimensions rd
        JOIN reviews r ON r.id = rd.review_id
        JOIN companies c ON c.id = r.company_id
        WHERE rd.analysis_version = 'v1'
          AND r.is_event_review = false
          AND (
            c.slug NOT IN :slugs
            OR (c.slug IN :slugs AND r.sample_type = 'chronological')
          )
        ORDER BY r.company_id, rd.dimension_id
    """), {"slugs": tuple(slugs_list)}).fetchall()

    print(f"     {len(rows):,} review_dimensions carregadas (após filtro sample_type)")

    data: dict = {}
    for row in rows:
        (company_id, data_review, nota, dim_id,
         sentiment, intensity, quote, temas_raw) = row

        temas = safe_json_loads(temas_raw)
        data.setdefault(company_id, {}).setdefault(dim_id, []).append({
            "data_review": data_review,
            "nota":        nota,
            "sentiment":   sentiment,
            "intensity":   intensity or 5,
            "quote":       quote or "",
            "temas":       temas,
        })

    # Total de reviews por empresa para mention_rate — com mesmo filtro
    total_reviews_map = {}
    for (cid, total) in session.execute(text("""
        SELECT r.company_id, COUNT(*)
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.is_event_review = false
          AND r.analysis_version IS NOT NULL
          AND (
            c.slug NOT IN :slugs
            OR (c.slug IN :slugs AND r.sample_type = 'chronological')
          )
        GROUP BY r.company_id
    """), {"slugs": tuple(slugs_list)}).fetchall():
        total_reviews_map[cid] = total

    now = datetime.now()
    periods = {
        "all":      lambda d: True,
        "last_6m":  lambda d: d and (now.date() - d).days <= 180,
        "last_12m": lambda d: d and (now.date() - d).days <= 365,
        "2022":     lambda d: d and d.year == 2022,
        "2023":     lambda d: d and d.year == 2023,
        "2024":     lambda d: d and d.year == 2024,
        "2025":     lambda d: d and d.year == 2025,
        "2026":     lambda d: d and d.year == 2026,
    }

    stats_rows = []

    for company_id, dims in tqdm(data.items(), desc="     Empresas"):
        total_co = total_reviews_map.get(company_id, 1)
        for dim_id, entries in dims.items():
            for period_name, period_filter in periods.items():
                filtered = [e for e in entries if period_filter(e["data_review"])]
                if not filtered:
                    continue

                pos   = sum(1 for e in filtered if e["sentiment"] == "positivo")
                neg   = sum(1 for e in filtered if e["sentiment"] == "negativo")
                mix   = sum(1 for e in filtered if e["sentiment"] == "misto")
                neu   = sum(1 for e in filtered if e["sentiment"] == "neutro")
                total = len(filtered)

                avg_intensity = round(sum(e["intensity"] for e in filtered) / total, 2)
                mention_rate  = round(total / total_co, 3)

                all_temas = []
                for e in filtered:
                    all_temas.extend(e["temas"])
                top_themes = [
                    {"tema": t, "count": c}
                    for t, c in Counter(all_temas).most_common(10)
                ]

                pos_entries = sorted(
                    [e for e in filtered if e["sentiment"] == "positivo" and e["quote"]],
                    key=lambda x: x["intensity"], reverse=True
                )[:3]
                neg_entries = sorted(
                    [e for e in filtered if e["sentiment"] == "negativo" and e["quote"]],
                    key=lambda x: x["intensity"], reverse=True
                )[:3]

                stats_rows.append({
                    "company_id":          company_id,
                    "dimension_id":        dim_id,
                    "analysis_version":    ANALYSIS_VERSION,
                    "period":              period_name,
                    "total_mentions":      total,
                    "positive_count":      pos,
                    "negative_count":      neg,
                    "mixed_count":         mix,
                    "neutral_count":       neu,
                    "sentiment_score":     calc_sentiment_score(pos, mix, neu, neg),
                    "avg_intensity":       avg_intensity,
                    "mention_rate":        mention_rate,
                    "top_themes":          safe_json_dumps(top_themes),
                    "top_positive_quotes": safe_json_dumps(
                        [{"quote": e["quote"], "intensity": e["intensity"]} for e in pos_entries]
                    ),
                    "top_negative_quotes": safe_json_dumps(
                        [{"quote": e["quote"], "intensity": e["intensity"]} for e in neg_entries]
                    ),
                })

    if dry_run:
        print(f"\n  [DRY RUN] {len(stats_rows)} registros seriam gravados — nenhum salvo.")
        _print_dry_run_preview(session, stats_rows)
        return 0

    if stats_rows:
        session.execute(
            text("""
                INSERT INTO company_dimension_stats (
                    company_id, dimension_id, analysis_version, period,
                    total_mentions, positive_count, negative_count,
                    mixed_count, neutral_count, sentiment_score,
                    avg_intensity, mention_rate, top_themes,
                    top_positive_quotes, top_negative_quotes
                ) VALUES (
                    :company_id, :dimension_id, :analysis_version, :period,
                    :total_mentions, :positive_count, :negative_count,
                    :mixed_count, :neutral_count, :sentiment_score,
                    :avg_intensity, :mention_rate, :top_themes,
                    :top_positive_quotes, :top_negative_quotes
                )
            """),
            stats_rows,
        )
        session.commit()

    return len(stats_rows)


def _print_dry_run_preview(session, stats_rows: list):
    company_names = {
        row[0]: row[1] for row in
        session.execute(text("SELECT id, name FROM companies")).fetchall()
    }
    dim_names = {
        row[0]: row[1] for row in
        session.execute(text("SELECT id, name FROM dimensions")).fetchall()
    }

    by_company: dict = {}
    for r in stats_rows:
        if r["period"] != "all":
            continue
        by_company.setdefault(r["company_id"], []).append(r)

    print("\n  Preview scores 'all':")
    print(f"  {'Empresa':<22} {'Dimensão':<25} {'Score':>6} {'Pos':>5} {'Neg':>5} {'Total':>7}")
    print(f"  {'-'*72}")
    for cid, rows in sorted(by_company.items()):
        co_name = company_names.get(cid, str(cid))
        sorted_rows = sorted(rows, key=lambda x: -x["sentiment_score"])
        for r in sorted_rows:
            dim_name = dim_names.get(r["dimension_id"], str(r["dimension_id"]))
            icon = "✅" if r["sentiment_score"] >= 6 else "⚠️" if r["sentiment_score"] >= 4 else "🔴"
            print(
                f"  {co_name:<22} {dim_name:<25} "
                f"{icon}{r['sentiment_score']:>4.1f} "
                f"{r['positive_count']:>5} {r['negative_count']:>5} "
                f"{r['total_mentions']:>7}"
            )
        avg = sum(r["sentiment_score"] for r in rows) / len(rows)
        print(f"  {'':22} {'MÉDIA':25} {avg:>6.1f}")
        print()


def print_scorecard_v2(session):
    companies  = session.execute(
        text("SELECT id, name, slug FROM companies WHERE is_active = true ORDER BY is_target DESC")
    ).fetchall()
    dimensions = session.execute(
        text("SELECT id, slug, name FROM dimensions WHERE is_active = true ORDER BY display_order")
    ).fetchall()

    print("\n" + "=" * 65)
    print(f"  📊 SCORECARD v2 — Período: ALL TIME")
    print("=" * 65)

    for company_id, company_name, slug in companies:
        sample_filter = (
            "AND r.sample_type = 'chronological'"
            if slug in STRATIFIED_COMPANIES else ""
        )

        totals = session.execute(text(f"""
            SELECT COUNT(*), AVG(r.avaliacao_geral),
                   SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END)
            FROM reviews r
            WHERE r.company_id = :cid
              AND r.is_event_review = false
              AND r.analysis_version IS NOT NULL
              {sample_filter}
        """), {"cid": company_id}).fetchone()

        total, avg_nota, pos_count, neg_count = totals
        if not total:
            continue

        chron_tag  = " [chronological only]" if slug in STRATIFIED_COMPANIES else ""
        target_tag = " 🎯 TARGET" if slug == "c6_bank" else ""

        print(f"\n  🏢 {company_name}{target_tag}{chron_tag}")
        print(f"     Reviews: {total} | Nota média: {avg_nota:.1f}/5 | "
              f"Positivas: {round((pos_count or 0)/total*100)}% | "
              f"Negativas: {round((neg_count or 0)/total*100)}%")
        print(f"\n     {'Dimensão':<25} {'Score':>6} {'Menções':>8}  Top quote negativo")
        print(f"     {'-'*75}")

        for dim_id, dim_slug, dim_name in dimensions:
            stat = session.execute(text("""
                SELECT sentiment_score, total_mentions, top_negative_quotes
                FROM company_dimension_stats
                WHERE company_id = :cid AND dimension_id = :did
                  AND period = 'all' AND analysis_version = :v
            """), {"cid": company_id, "did": dim_id, "v": ANALYSIS_VERSION}).fetchone()

            if not stat or not stat[1]:
                print(f"     {dim_name:<25} {'N/A':>6} {'0':>8}")
                continue

            score, mentions, neg_quotes_raw = stat
            neg_quotes = safe_json_loads(neg_quotes_raw)
            top_neg    = ""
            if neg_quotes:
                top_neg = f'"{str(neg_quotes[0].get("quote",""))[:45]}..."'

            icon = "✅" if score >= 6 else "⚠️ " if score >= 4 else "🔴"
            print(f"     {dim_name:<25} {icon}{score:>4.1f}  {mentions:>7}  {top_neg}")


def main():
    parser = argparse.ArgumentParser(description="Aggregate v2")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra scores sem persistir.")
    args = parser.parse_args()

    print("=" * 65)
    print("  Pipeline 04 — Agregações estratégicas (v2)")
    print(f"  Versão: {ANALYSIS_VERSION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:
        n_stats = aggregate_dimension_stats(session, dry_run=args.dry_run)

        if not args.dry_run:
            print(f"\n  ✅ {n_stats} registros de stats calculados")
            print_scorecard_v2(session)
            print(f"\n{'=' * 65}")
            print(f"  ✅ Agregações v2 concluídas")
            print(f"{'=' * 65}")
            print(f"\n🚀 Próximo passo: python pipeline/07_insights_macro_v2.py")


if __name__ == "__main__":
    main()