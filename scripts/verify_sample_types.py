"""
verify_sample_types.py
======================
Roda APÓS a migration e ANTES do pipeline v2.
Mostra contagem de reviews por empresa e sample_type para confirmar
que a migration marcou corretamente as reviews estratificadas.

Uso:
    python scripts/verify_sample_types.py
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as conn:
    print("\n" + "=" * 65)
    print("VERIFICAÇÃO DE SAMPLE TYPES")
    print("=" * 65)

    rows = conn.execute(text("""
        SELECT c.name, c.slug,
               r.sample_type,
               COUNT(*) AS total,
               ROUND(AVG(r.avaliacao_geral)::numeric, 2) AS avg_nota,
               SUM(CASE WHEN r.sentimento_geral = 'positivo' THEN 1 ELSE 0 END) AS pos,
               SUM(CASE WHEN r.sentimento_geral = 'negativo' THEN 1 ELSE 0 END) AS neg
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.is_event_review = false
          AND r.analysis_version IS NOT NULL
        GROUP BY c.name, c.slug, c.is_target, r.sample_type
        ORDER BY c.is_target DESC, c.name, r.sample_type
    """)).fetchall()

    current_company = None
    for name, slug, stype, total, avg_nota, pos, neg in rows:
        if name != current_company:
            print(f"\n  {name} ({slug})")
            current_company = name
        mix = total - (pos or 0) - (neg or 0)
        score = round(((pos or 0) + mix * 0.5) / total * 10, 1) if total else 0
        tag = " ← será usado no v2" if stype == "chronological" else " ← só RAG"
        print(f"    [{stype:14}] {total:4} reviews · nota {avg_nota:.1f} · score {score:.1f}/10{tag}")

    # Reviews novas (sem analysis_version ainda) — aguardando pipeline 03
    pending = conn.execute(text("""
        SELECT c.name, COUNT(*) AS total
        FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE r.analysis_version IS NULL
          AND r.is_event_review = false
        GROUP BY c.name
        ORDER BY c.name
    """)).fetchall()

    if pending:
        print("\n" + "-" * 65)
        print("⏳ Reviews pendentes de análise (pipeline 03):")
        for name, total in pending:
            print(f"    {name}: {total} reviews")
    else:
        print("\n  ⚠️  Nenhuma review nova encontrada — rode o 01_ingest.py primeiro")

    print("\n" + "=" * 65)

    # Checagem rápida: tem reviews chronological do C6/Nubank?
    ok = conn.execute(text("""
        SELECT COUNT(*) FROM reviews r
        JOIN companies c ON c.id = r.company_id
        WHERE c.slug IN ('c6_bank', 'nubank')
          AND r.sample_type = 'chronological'
          AND r.analysis_version IS NOT NULL
    """)).scalar()

    if ok and ok > 0:
        print(f"\n✓ {ok} reviews chronological prontas para o aggregate v2\n")
    else:
        print("\n⚠️  Ainda não há reviews chronological analisadas para C6/Nubank.")
        print("   Rode: python pipeline/01_ingest.py → depois 03_analyze_micro.py\n")