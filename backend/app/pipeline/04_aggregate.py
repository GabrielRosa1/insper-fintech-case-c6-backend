#!/usr/bin/env python3
"""
Pipeline Step 04 — Agregações estratégicas

Calcula e persiste:
  • company_dimension_stats por empresa × dimensão × período
  • Sentimento médio por empresa ao longo do tempo (mensal)
  • Top temas emergentes por empresa
  • Comparação direta C6 Bank vs Nubank por dimensão

Idempotente: limpa e recalcula para a analysis_version atual.

Uso:
    cd backend/
    python -m app.pipeline.04_aggregate
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from sqlalchemy import text
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session
from app.config import get_settings

settings = get_settings()
ANALYSIS_VERSION = settings.analysis_version


# ── Helpers JSON (PostgreSQL já deserializa JSON automaticamente) ─────────────

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


# ── Score ─────────────────────────────────────────────────────────────────────

def calc_sentiment_score(pos: int, mix: int, neu: int, neg: int) -> float:
    """Score ponderado 0-10."""
    total = pos + mix + neu + neg
    if total == 0:
        return 5.0
    raw = (pos * 1.0 + mix * 0.5 + neu * 0.5 + neg * 0.0) / total
    return round(raw * 10, 2)


# ── Agregação principal ───────────────────────────────────────────────────────

def aggregate_dimension_stats(session) -> int:
    print("\n  📊 Calculando stats por empresa × dimensão × período...")

    session.execute(
        text("DELETE FROM company_dimension_stats WHERE analysis_version = :v"),
        {"v": ANALYSIS_VERSION}
    )
    session.commit()

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
        WHERE rd.analysis_version = :v
          AND r.is_event_review = false
        ORDER BY r.company_id, rd.dimension_id
    """), {"v": ANALYSIS_VERSION}).fetchall()

    print(f"     {len(rows):,} review_dimensions carregadas")

    # Organiza: {company_id: {dim_id: [entries]}}
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

    # Total de reviews por empresa para mention_rate
    total_reviews_map = {}
    for (cid, total) in session.execute(text("""
        SELECT company_id, COUNT(*) FROM reviews
        WHERE is_event_review = false AND analysis_version IS NOT NULL
        GROUP BY company_id
    """)).fetchall():
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


# ── Scorecard ─────────────────────────────────────────────────────────────────

def print_company_health(session):
    companies  = session.execute(
        text("SELECT id, name, slug FROM companies WHERE is_active = true ORDER BY is_target DESC")
    ).fetchall()
    dimensions = session.execute(
        text("SELECT id, slug, name FROM dimensions WHERE is_active = true ORDER BY display_order")
    ).fetchall()

    print("\n" + "=" * 65)
    print("  📊 SCORECARD — Período: ALL TIME")
    print("=" * 65)

    for company_id, company_name, slug in companies:
        totals = session.execute(text("""
            SELECT COUNT(*), AVG(avaliacao_geral),
                   SUM(CASE WHEN sentimento_geral = 'positivo' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sentimento_geral = 'negativo' THEN 1 ELSE 0 END)
            FROM reviews
            WHERE company_id = :cid AND is_event_review = false
              AND analysis_version IS NOT NULL
        """), {"cid": company_id}).fetchone()

        total, avg_nota, pos_count, neg_count = totals
        if not total:
            continue

        pos_pct = round((pos_count or 0) / total * 100)
        neg_pct = round((neg_count or 0) / total * 100)
        target_tag = " 🎯 TARGET" if slug == "c6_bank" else ""

        print(f"\n  🏢 {company_name}{target_tag}")
        print(f"     Reviews: {total} | Nota média: {avg_nota:.1f}/5 | "
              f"Positivas: {pos_pct}% | Negativas: {neg_pct}%")
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
            top_neg = ""
            if neg_quotes:
                top_neg = f'"{str(neg_quotes[0].get("quote",""))[:45]}..."'

            icon = "✅" if score >= 6 else "⚠️ " if score >= 4 else "🔴"
            print(f"     {dim_name:<25} {icon}{score:>4.1f}  {mentions:>7}  {top_neg}")


def print_comparison(session):
    print("\n" + "=" * 65)
    print("  ⚔️  COMPARAÇÃO DIRETA: C6 Bank vs Nubank")
    print("=" * 65)

    c6_id = session.execute(text("SELECT id FROM companies WHERE slug = 'c6_bank'")).scalar()
    nu_id = session.execute(text("SELECT id FROM companies WHERE slug = 'nubank'")).scalar()
    dims  = session.execute(
        text("SELECT id, name FROM dimensions WHERE is_active = true ORDER BY display_order")
    ).fetchall()

    if not c6_id or not nu_id:
        return

    print(f"\n  {'Dimensão':<25} {'C6 Bank':>10} {'Nubank':>10}  Vantagem")
    print(f"  {'-'*62}")

    for dim_id, dim_name in dims:
        c6 = session.execute(text("""
            SELECT sentiment_score FROM company_dimension_stats
            WHERE company_id = :cid AND dimension_id = :did
              AND period = 'all' AND analysis_version = :v
        """), {"cid": c6_id, "did": dim_id, "v": ANALYSIS_VERSION}).scalar()

        nu = session.execute(text("""
            SELECT sentiment_score FROM company_dimension_stats
            WHERE company_id = :cid AND dimension_id = :did
              AND period = 'all' AND analysis_version = :v
        """), {"cid": nu_id, "did": dim_id, "v": ANALYSIS_VERSION}).scalar()

        c6_s = f"{c6:.1f}" if c6 is not None else "N/A"
        nu_s = f"{nu:.1f}" if nu is not None else "N/A"

        if c6 is not None and nu is not None:
            diff = c6 - nu
            if diff > 0.5:
                vantagem = f"✅ C6 Bank (+{diff:.1f})"
            elif diff < -0.5:
                vantagem = f"🟣 Nubank (+{abs(diff):.1f})"
            else:
                vantagem = "⚖️  Empate"
        else:
            vantagem = "—"

        print(f"  {dim_name:<25} {c6_s:>10} {nu_s:>10}  {vantagem}")


def print_top_temas(session):
    print("\n" + "=" * 65)
    print("  🔍 TOP TEMAS EMERGENTES (detectados pela IA)")
    print("=" * 65)

    companies = session.execute(
        text("SELECT id, name FROM companies WHERE is_active = true ORDER BY is_target DESC")
    ).fetchall()

    for company_id, company_name in companies:
        rows = session.execute(text("""
            SELECT temas_emergentes FROM reviews
            WHERE company_id = :cid
              AND is_event_review = false
              AND temas_emergentes IS NOT NULL
              AND analysis_version IS NOT NULL
        """), {"cid": company_id}).fetchall()

        all_temas = []
        for (temas_raw,) in rows:
            all_temas.extend(safe_json_loads(temas_raw))

        top = Counter(all_temas).most_common(15)
        print(f"\n  🏢 {company_name}")
        for tema, count in top:
            bar = "█" * count
            print(f"     {tema[:50]:<50} {count:3d}  {bar}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Pipeline 04 — Agregações estratégicas")
    print(f"  Version: {ANALYSIS_VERSION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:
        n_stats = aggregate_dimension_stats(session)
        print(f"\n  ✅ {n_stats} registros de stats calculados")

        print_company_health(session)
        print_comparison(session)
        print_top_temas(session)

        print(f"\n{'=' * 65}")
        print(f"  ✅ Agregações concluídas")
        print(f"{'=' * 65}")
        print(f"\n🚀 Próximo passo: python -m app.pipeline.05_detect_events")


if __name__ == "__main__":
    main()