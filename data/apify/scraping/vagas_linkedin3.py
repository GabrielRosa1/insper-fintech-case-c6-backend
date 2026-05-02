"""
scraping_vagas.py v8
====================
Estratégia: 4 buscas por empresa (uma por área do case).
Cada busca agrupa múltiplos f_CF relacionados numa única URL.

    Tecnologia  → f_CF=4,8,2   (Engenharia + TI + Dados)
    Negócios    → f_CF=9,13,10  (Marketing + Vendas + Produto)
    Operações   → f_CF=14,15    (Operações + Suporte)
    Corporativo → f_CF=3,26,7,21 (Finanças + Jurídico + RH + Admin)

Vantagens vs versões anteriores:
    v6 (12 buscas): 96 runs, muitas duplicatas, muito lento
    v7 (1 busca):   8 runs, rápido, mas perde vagas por limite do LI
    v8 (4 buscas):  32 runs, cobertura máxima, duplicatas mínimas

TEMPO ESTIMADO: ~45-60 minutos para 8 empresas

DEPLOY SEMANAL:
    Troque TIME_FILTER para "r604800" (última semana).
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from apify_client import ApifyClient
from collections import Counter

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
SCRIPT_DIR  = Path(__file__).parent
OUTPUT_DIR  = SCRIPT_DIR.parent

ACTOR_ID    = "curious_coder/linkedin-jobs-scraper"
MAX_RESULTS = 300
TIME_FILTER = "r2592000"

COMPANIES = [
    {"name": "iFood",            "slug": "ifood",     "f_C": "247645%2C101015933"},
    {"name": "BTG Pactual",      "slug": "btg",       "f_C": "654090%2C53185306%2C71627692%2C3188881%2C11767688%2C22953308"},
    {"name": "Santander Brasil", "slug": "santander", "f_C": "434631%2C66197178%2C83543692"},
]

# 4 grupos de área — f_CF múltiplos numa única URL
AREA_GROUPS = [
    {
        "area":  "tecnologia",
        "label": "Tecnologia (Eng + TI + Dados)",
        "f_CF":  "4%2C8%2C2",   # 4=Engenharia, 8=TI, 2=Dados
    },
    {
        "area":  "negocios",
        "label": "Negócios (Mktg + Vendas + Produto)",
        "f_CF":  "9%2C13%2C10", # 9=Marketing, 13=Vendas, 10=Produto
    },
    {
        "area":  "operacoes",
        "label": "Operações (Ops + Suporte)",
        "f_CF":  "14%2C15",     # 14=Operações, 15=Suporte
    },
    {
        "area":  "corporativo",
        "label": "Corporativo (Fin + Jur + RH + Admin)",
        "f_CF":  "3%2C26%2C7%2C21", # 3=Finanças, 26=Jurídico, 7=RH, 21=Admin
    },
]


def build_url(f_C: str, f_CF: str) -> str:
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?f_C={f_C}"
        f"&f_CF={f_CF}"
        "&geoId=106057199"
        "&keywords="
        f"&f_TPR={TIME_FILTER}"
    )


def deduplicar(jobs: list) -> list:
    seen, unique = set(), []
    for job in jobs:
        jid = job.get("id") or job.get("link", "")
        if jid and jid not in seen:
            seen.add(jid)
            unique.append(job)
        elif not jid:
            unique.append(job)
    return unique


def run():
    if not APIFY_TOKEN:
        raise ValueError("APIFY_TOKEN não encontrado no .env")

    client   = ApifyClient(APIFY_TOKEN)
    all_jobs = []
    erros    = []
    total    = len(COMPANIES)

    print("=" * 60)
    print("LinkedIn Jobs v8 — 4 buscas por empresa")
    print(f"Empresas: {total} | Áreas: 4 | Total runs: {total * 4}")
    print(f"Max por busca: {MAX_RESULTS}")
    print("=" * 60)

    for company in COMPANIES:
        company_jobs = []
        print(f"\n[{company['name']}]")

        for group in AREA_GROUPS:
            url = build_url(company["f_C"], group["f_CF"])

            run_input = {
                "urls":            [url],
                "maxResults":      MAX_RESULTS,
                "parseJobDetails": True,
            }

            try:
                run   = client.actor(ACTOR_ID).call(run_input=run_input)
                items = list(
                    client.dataset(run["defaultDatasetId"]).iterate_items()
                )
                for item in items:
                    item["_meta_company"] = company["name"]
                    item["_meta_slug"]    = company["slug"]
                    item["_meta_area"]    = group["area"]
                company_jobs.extend(items)
                print(f"  {group['label']:<38} → {len(items)} vagas")

            except Exception as e:
                erros.append(f"{company['name']} / {group['area']}: {e}")
                print(f"  {group['label']:<38} → ✗ {e}")

            time.sleep(1.5)

        # Deduplicar por empresa antes de somar
        antes        = len(company_jobs)
        company_jobs = deduplicar(company_jobs)
        depois       = len(company_jobs)
        all_jobs.extend(company_jobs)
        print(f"  → {depois} vagas únicas ({antes - depois} duplicatas removidas)")

    # Deduplicação global
    total_antes = len(all_jobs)
    all_jobs    = deduplicar(all_jobs)
    total_depois = len(all_jobs)

    # Salvar
    ts          = datetime.now().strftime("%Y%m%d_%H%M")
    output_main = OUTPUT_DIR / "vagas_todas_areas.json"
    output_bkp  = OUTPUT_DIR / f"vagas_{ts}.json"

    for path in [output_main, output_bkp]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Total bruto        : {total_antes}")
    print(f"✓ Total deduplicado  : {total_depois}")
    print(f"  Arquivo principal  : {output_main}")
    print(f"  Backup             : {output_bkp}")
    print(f"{'='*60}\n")

    counter = Counter(j.get("_meta_company","?") for j in all_jobs)
    print("Resumo por empresa:")
    for name, count in sorted(counter.items(), key=lambda x: -x[1]):
        ok = "✓" if count >= 20 else "⚠ "
        print(f"  {ok} {name:<25} | {count} vagas")

    area_counter = Counter(
        (j.get("_meta_company","?"), j.get("_meta_area","?"))
        for j in all_jobs
    )
    print("\nPor empresa + área:")
    for (emp, area), count in sorted(area_counter.items(), key=lambda x: (-x[1])):
        print(f"  {emp:<22} | {area:<12} | {count}")

    if erros:
        print(f"\n⚠  {len(erros)} erros:")
        for e in erros:
            print(f"  - {e}")


if __name__ == "__main__":
    run()