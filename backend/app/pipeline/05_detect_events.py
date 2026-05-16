#!/usr/bin/env python3
"""
Pipeline Step 05 — Detecção de eventos divisores de águas

Detecta automaticamente momentos em que o sentimento mudou
significativamente, indicando eventos marcantes (layoffs, mudanças
de política, RTO, IPO, etc.).

Algoritmo:
  1. Calcula sentimento médio mensal por empresa
  2. Detecta change-points: meses com delta > threshold vs média móvel
  3. Agrupa change-points próximos em eventos
  4. Persiste em company_events com sentiment_before/after/delta

Também cadastra eventos conhecidos manualmente (RTO Nubank, layoff C6).

Uso:
    cd backend/
    python -m app.pipeline.05_detect_events
"""

import sys
import json
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session
from app.config import get_settings

settings = get_settings()
ANALYSIS_VERSION = settings.analysis_version

# Threshold: delta de sentimento que caracteriza um evento
CHANGE_THRESHOLD = 1.5  # pontos no score 0-10


# ── Eventos conhecidos (seed manual) ─────────────────────────────────────────

KNOWN_EVENTS = [
    {
        "slug":        "c6_bank",
        "nome":        "Layoff C6 Bank",
        "descricao":   "Demissão em massa no C6 Bank, reportada em diversas reviews como divisor de águas cultural e de confiança.",
        "event_type":  "layoff",
        "data_evento": date(2023, 2, 1),
        "source":      "manual",
        "is_confirmed": True,
    },
    {
        "slug":        "nubank",
        "nome":        "IPO Nubank (NYSE)",
        "descricao":   "Abertura de capital do Nubank na NYSE. Início da transição de startup para empresa pública com pressão por resultados trimestrais.",
        "event_type":  "ipo",
        "data_evento": date(2021, 12, 9),
        "source":      "manual",
        "is_confirmed": True,
    },
    {
        "slug":        "nubank",
        "nome":        "Anúncio RTO Nubank",
        "descricao":   "Anúncio do retorno ao trabalho presencial/híbrido em novembro de 2025. Maior divisor de águas identificado nas reviews — domina 40-50% das reclamações recentes.",
        "event_type":  "rto",
        "data_evento": date(2025, 11, 1),
        "source":      "manual",
        "is_confirmed": True,
    },
    {
        "slug":        "nubank",
        "nome":        "Pressão AI-First Nubank",
        "descricao":   "Imposição de metas de uso de IA sem treinamento ou direcionamento claro. Gerou ansiedade e cobranças desproporcionais relatadas em reviews de 2025-2026.",
        "event_type":  "politica",
        "data_evento": date(2025, 6, 1),
        "source":      "manual",
        "is_confirmed": True,
    },
]


# ── Cálculo de sentimento mensal ──────────────────────────────────────────────

def get_monthly_sentiment(session, company_id: int) -> dict:
    """
    Retorna {(year, month): {"score": float, "count": int}} para uma empresa.
    Score = média ponderada de sentimento_geral das reviews naquele mês.
    """
    rows = session.execute(text("""
        SELECT
            EXTRACT(YEAR  FROM data_review)::int AS yr,
            EXTRACT(MONTH FROM data_review)::int AS mo,
            sentimento_geral,
            COUNT(*) as cnt
        FROM reviews
        WHERE company_id = :cid
          AND data_review IS NOT NULL
          AND sentimento_geral IS NOT NULL
          AND is_event_review = false
          AND analysis_version IS NOT NULL
        GROUP BY yr, mo, sentimento_geral
        ORDER BY yr, mo
    """), {"cid": company_id}).fetchall()

    SENTIMENT_KEY = {"positivo": "pos", "negativo": "neg", "misto": "mix", "neutro": "neu"}

    # Agrega por mês
    monthly: dict = defaultdict(lambda: {"pos": 0, "neg": 0, "mix": 0, "neu": 0, "total": 0})
    for yr, mo, sentiment, cnt in rows:
        key = (int(yr), int(mo))
        mapped = SENTIMENT_KEY.get(str(sentiment).lower(), "neu")
        monthly[key][mapped]      += cnt
        monthly[key]["total"]     += cnt

    result = {}
    for (yr, mo), counts in monthly.items():
        total = counts["total"]
        if total < 2:  # ignora meses com poucos dados
            continue
        pos = counts.get("pos", 0)
        mix = counts.get("mix", 0)
        neg = counts.get("neg", 0)
        score = ((pos * 1.0 + mix * 0.5 + neg * 0.0) / total) * 10
        result[(yr, mo)] = {"score": round(score, 2), "count": total}

    return result


def moving_average(data: list[float], window: int = 3) -> list[float]:
    """Média móvel simples."""
    result = []
    for i in range(len(data)):
        start = max(0, i - window + 1)
        window_data = data[start:i + 1]
        result.append(sum(window_data) / len(window_data))
    return result


# ── Detecção automática de change-points ─────────────────────────────────────

def detect_change_points(monthly: dict, threshold: float) -> list[dict]:
    """
    Detecta meses com mudança brusca no sentimento.
    Retorna lista de {year, month, score, delta, direction}.
    """
    if len(monthly) < 4:
        return []

    sorted_keys = sorted(monthly.keys())
    scores = [monthly[k]["score"] for k in sorted_keys]
    counts = [monthly[k]["count"] for k in sorted_keys]
    ma     = moving_average(scores, window=3)

    change_points = []
    for i in range(2, len(scores)):
        delta = scores[i] - ma[i - 1]
        if abs(delta) >= threshold and counts[i] >= 3:
            yr, mo = sorted_keys[i]
            change_points.append({
                "year":      yr,
                "month":     mo,
                "score":     scores[i],
                "ma_before": round(ma[i - 1], 2),
                "delta":     round(delta, 2),
                "direction": "melhora" if delta > 0 else "piora",
                "count":     counts[i],
            })

    return change_points


# ── Calcula sentimento before/after para um evento ───────────────────────────

def calc_event_impact(session, company_id: int, event_date: date) -> dict:
    """Calcula sentimento médio 3 meses antes e 3 meses depois do evento."""

    def avg_score(rows_data):
        if not rows_data:
            return None
        sents = [str(r).lower() if r else "neutro" for r in rows_data]
        pos   = sum(1 for s in sents if s == "positivo")
        mix   = sum(1 for s in sents if s == "misto")
        neg   = sum(1 for s in sents if s == "negativo")
        total = len(sents)
        return round(((pos * 1.0 + mix * 0.5 + neg * 0.0) / total) * 10, 2)

    before = session.execute(text("""
        SELECT sentimento_geral FROM reviews
        WHERE company_id = :cid
          AND data_review BETWEEN :start AND :end
          AND sentimento_geral IS NOT NULL
          AND is_event_review = false
    """), {
        "cid":   company_id,
        "start": date(event_date.year - (1 if event_date.month <= 3 else 0),
                      (event_date.month - 3 - 1) % 12 + 1, 1),
        "end":   event_date,
    }).fetchall()

    after = session.execute(text("""
        SELECT sentimento_geral FROM reviews
        WHERE company_id = :cid
          AND data_review BETWEEN :start AND :end
          AND sentimento_geral IS NOT NULL
          AND is_event_review = false
    """), {
        "cid":   company_id,
        "start": event_date,
        "end":   date(event_date.year + (1 if event_date.month >= 10 else 0),
                      (event_date.month + 2) % 12 + 1, 1),
    }).fetchall()

    before_score = avg_score([r[0] for r in before])
    after_score  = avg_score([r[0] for r in after])
    delta        = round(after_score - before_score, 2) if (before_score and after_score) else None

    return {
        "sentiment_before": before_score,
        "sentiment_after":  after_score,
        "sentiment_delta":  delta,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Pipeline 05 — Detecção de eventos divisores de águas")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:

        companies = session.execute(
            text("SELECT id, name, slug FROM companies WHERE is_active = true")
        ).fetchall()

        company_map = {slug: (id_, name) for id_, name, slug in companies}

        # Limpa eventos auto-detectados (mantém manuais confirmados)
        session.execute(text("""
            DELETE FROM company_events
            WHERE source = 'auto_detected'
        """))
        session.commit()

        all_events = []

        for company_id, company_name, slug in companies:
            print(f"\n  🏢 {company_name}")

            monthly = get_monthly_sentiment(session, company_id)
            print(f"     {len(monthly)} meses com dados")

            if not monthly:
                continue

            # Imprime linha do tempo de sentimento
            print(f"\n     📅 Sentimento mensal (score 0-10):")
            sorted_months = sorted(monthly.keys())
            for yr, mo in sorted_months:
                m = monthly[(yr, mo)]
                bar_len = int(m["score"] / 10 * 20)
                bar = "█" * bar_len
                icon = "🟢" if m["score"] >= 6 else "🟡" if m["score"] >= 4 else "🔴"
                print(f"     {icon} {yr}-{mo:02d}  {m['score']:4.1f}  {bar}  (n={m['count']})")

            # Detecta change-points automaticamente
            cps = detect_change_points(monthly, CHANGE_THRESHOLD)
            if cps:
                print(f"\n     ⚡ {len(cps)} change-points detectados:")
                for cp in cps:
                    arrow = "📈" if cp["direction"] == "melhora" else "📉"
                    print(f"       {arrow} {cp['year']}-{cp['month']:02d}: "
                          f"score={cp['score']} delta={cp['delta']:+.1f} "
                          f"(antes: {cp['ma_before']}) n={cp['count']}")

                    # Persiste change-point como evento auto-detectado
                    event_date = date(cp["year"], cp["month"], 1)
                    impact     = calc_event_impact(session, company_id, event_date)

                    all_events.append({
                        "company_id":          company_id,
                        "nome":                f"Mudança de sentimento {cp['year']}-{cp['month']:02d}",
                        "descricao":           f"Change-point automático: score foi de {cp['ma_before']} para {cp['score']} (delta={cp['delta']:+.1f})",
                        "event_type":          "outro",
                        "data_evento":         event_date,
                        "source":              "auto_detected",
                        "sentiment_before":    impact["sentiment_before"],
                        "sentiment_after":     impact["sentiment_after"],
                        "sentiment_delta":     impact["sentiment_delta"],
                        "review_volume_delta": None,
                        "confidence":          min(abs(cp["delta"]) / 5, 1.0),
                        "is_confirmed":        False,
                    })

        # Insere eventos auto-detectados
        if all_events:
            session.execute(
                text("""
                    INSERT INTO company_events (
                        company_id, nome, descricao, event_type, data_evento,
                        source, sentiment_before, sentiment_after, sentiment_delta,
                        review_volume_delta, confidence, is_confirmed
                    ) VALUES (
                        :company_id, :nome, :descricao, :event_type, :data_evento,
                        :source, :sentiment_before, :sentiment_after, :sentiment_delta,
                        :review_volume_delta, :confidence, :is_confirmed
                    )
                """),
                all_events,
            )
            session.commit()
            print(f"\n  ✅ {len(all_events)} eventos auto-detectados inseridos")

        # Insere/atualiza eventos conhecidos manualmente
        print(f"\n  📌 Processando {len(KNOWN_EVENTS)} eventos conhecidos...")
        manual_inserted = 0
        for ev in KNOWN_EVENTS:
            slug = ev["slug"]
            if slug not in company_map:
                continue

            company_id = company_map[slug][0]

            # Verifica se já existe
            existing = session.execute(text("""
                SELECT id FROM company_events
                WHERE company_id = :cid AND nome = :nome AND source = 'manual'
            """), {"cid": company_id, "nome": ev["nome"]}).fetchone()

            if existing:
                continue

            impact = calc_event_impact(session, company_id, ev["data_evento"])

            session.execute(text("""
                INSERT INTO company_events (
                    company_id, nome, descricao, event_type, data_evento,
                    source, sentiment_before, sentiment_after, sentiment_delta,
                    confidence, is_confirmed
                ) VALUES (
                    :company_id, :nome, :descricao, :event_type, :data_evento,
                    :source, :sentiment_before, :sentiment_after, :sentiment_delta,
                    :confidence, :is_confirmed
                )
            """), {
                "company_id":       company_id,
                "nome":             ev["nome"],
                "descricao":        ev["descricao"],
                "event_type":       ev["event_type"],
                "data_evento":      ev["data_evento"],
                "source":           ev["source"],
                "sentiment_before": impact["sentiment_before"],
                "sentiment_after":  impact["sentiment_after"],
                "sentiment_delta":  impact["sentiment_delta"],
                "confidence":       1.0,
                "is_confirmed":     ev["is_confirmed"],
            })
            manual_inserted += 1

        session.commit()
        print(f"  ✅ {manual_inserted} eventos manuais inseridos")

        # Relatório final
        print(f"\n{'=' * 65}")
        print(f"  📊 EVENTOS CADASTRADOS")
        print(f"{'=' * 65}")

        events = session.execute(text("""
            SELECT ce.nome, ce.event_type, ce.data_evento,
                   ce.sentiment_delta, ce.source, ce.is_confirmed,
                   co.name as company_name
            FROM company_events ce
            JOIN companies co ON co.id = ce.company_id
            ORDER BY co.is_target DESC, ce.data_evento
        """)).fetchall()

        for nome, etype, data_ev, delta, source, confirmed, co_name in events:
            delta_str = f"Δ{delta:+.1f}" if delta else "Δ N/A"
            icon = "📌" if source == "manual" else "🤖"
            conf = "✅" if confirmed else "❓"
            print(f"  {icon}{conf} {co_name:<12} {str(data_ev)[:7]}  [{etype:<12}]  "
                  f"{delta_str:>8}  {nome[:45]}")

        print(f"\n{'=' * 65}")
        print(f"  ✅ Detecção de eventos concluída")
        print(f"{'=' * 65}")
        print(f"\n🚀 Próximo passo: python -m app.pipeline.06_gap_analysis")


if __name__ == "__main__":
    main()