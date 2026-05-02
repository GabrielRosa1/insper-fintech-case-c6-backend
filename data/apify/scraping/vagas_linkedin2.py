"""
scraping_vagas_faltantes.py
===========================
Coleta APENAS as empresas e áreas que faltaram no run anterior
por limite de crédito Apify.

O QUE FALTA COLETAR:
    Itaú Unibanco  — áreas: Produto, Operações, Suporte, Finanças,
                             Jurídico, RH, Administrativo
    XP Investimentos — todas as 12 áreas
    Bradesco         — todas as 12 áreas
    iFood            — todas as 12 áreas
    BTG Pactual      — todas as 12 áreas
    Santander Brasil — todas as 12 áreas

O QUE JÁ TEMOS (não recotar):
    C6 Bank       — 108 vagas (tecnologia) ✓
    Nubank        — 112 vagas (tecnologia) ✓
    Itaú Unibanco — 231 vagas (tecnologia parcial) ✓

SAÍDA:
    Salva em vagas_faltantes.json
    Depois merge com vagas_todas_areas.json via etl_merge.py
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

ACTOR_ID        = "curious_coder/linkedin-jobs-scraper"
MAX_PER_SEARCH  = 50
TIME_FILTER     = "r2592000"

# ─── ÁREAS FUNCIONAIS ────────────────────────────────────────────────────────
TODAS_AREAS = [
    {"code": "4",  "nome": "tecnologia",  "label": "Engenharia"},
    {"code": "8",  "nome": "tecnologia",  "label": "TI"},
    {"code": "2",  "nome": "dados",       "label": "Dados e Analytics"},
    {"code": "9",  "nome": "negocios",    "label": "Marketing"},
    {"code": "13", "nome": "negocios",    "label": "Vendas"},
    {"code": "10", "nome": "negocios",    "label": "Produto"},
    {"code": "14", "nome": "operacoes",   "label": "Operações"},
    {"code": "15", "nome": "operacoes",   "label": "Suporte"},
    {"code": "3",  "nome": "corporativo", "label": "Finanças"},
    {"code": "26", "nome": "corporativo", "label": "Jurídico"},
    {"code": "7",  "nome": "corporativo", "label": "RH"},
    {"code": "21", "nome": "corporativo", "label": "Administrativo"},
]

AREAS_ITAU_FALTANTES = [
    a for a in TODAS_AREAS
    if a["label"] in ["Produto", "Operações", "Suporte", "Finanças",
                       "Jurídico", "RH", "Administrativo"]
]

# ─── SEARCHES PENDENTES ───────────────────────────────────────────────────────
SEARCHES_PENDENTES = []

# Itaú — áreas que faltaram
for area in AREAS_ITAU_FALTANTES:
    SEARCHES_PENDENTES.append({
        "name": "Itaú Unibanco",
        "slug": "itau",
        "f_C":  "333329",
        "area": area,
    })

# Empresas que não foram coletadas — todas as 12 áreas
EMPRESAS_FALTANTES = [
    {"name": "XP Investimentos",  "slug": "xp",        "f_C": "11794476%2C14031303%2C2304919%2C144288%2C2540096"},
    {"name": "Bradesco",          "slug": "bradesco",   "f_C": "162778"},
    {"name": "iFood",             "slug": "ifood",      "f_C": "247645%2C101015933"},
    {"name": "BTG Pactual",       "slug": "btg",        "f_C": "654090%2C53185306%2C71627692%2C3188881%2C11767688%2C22953308"},
    {"name": "Santander Brasil",  "slug": "santander",  "f_C": "434631%2C66197178%2C83543692"},
]

for company in EMPRESAS_FALTANTES:
    for area in TODAS_AREAS:
        SEARCHES_PENDENTES.append({
            "name": company["name"],
            "slug": company["slug"],
            "f_C":  company["f_C"],
            "area": area,
        })


def build_url(f_C, f_CF):
    return (
        f"https://www.linkedin.com/jobs/search/"
        f"?f_C={f_C}&f_CF={f_CF}"
        f"&geoId=106057199&keywords=&f_TPR={TIME_FILTER}"
    )


def deduplicar(jobs):
    seen = set()
    unique = []
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
    total    = len(SEARCHES_PENDENTES)

    print("=" * 60)
    print("LinkedIn Jobs — Coleta das Empresas/Áreas Faltantes")
    print(f"Total de buscas pendentes: {total}")
    print(f"Estimativa: {total * MAX_PER_SEARCH} vagas máximo")
    print("=" * 60)

    current_company = None
    company_jobs = []

    for i, search in enumerate(SEARCHES_PENDENTES, 1):
        name  = search["name"]
        area  = search["area"]
        f_C   = search["f_C"]

        # Novo bloco de empresa
        if name != current_company:
            if current_company and company_jobs:
                antes   = len(company_jobs)
                uniq    = deduplicar(company_jobs)
                depois  = len(uniq)
                all_jobs.extend(uniq)
                print(f"  → {depois} vagas únicas ({antes - depois} duplicatas removidas)\n")
            current_company = name
            company_jobs = []
            print(f"\n[{name}]")

        url = build_url(f_C, area["code"])
        run_input = {
            "urls":            [url],
            "maxResults":      MAX_PER_SEARCH,
            "parseJobDetails": True,
        }

        try:
            run   = client.actor(ACTOR_ID).call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

            for item in items:
                item["_meta_company"]    = name
                item["_meta_slug"]       = search["slug"]
                item["_meta_area"]       = area["nome"]
                item["_meta_area_label"] = area["label"]

            company_jobs.extend(items)
            print(f"  {area['label']:<20} → {len(items)} vagas")

        except Exception as e:
            erros.append(f"{name} / {area['label']}: {e}")
            print(f"  {area['label']:<20} → ✗ {e}")

        time.sleep(1.5)

    # Flush última empresa
    if company_jobs:
        antes  = len(company_jobs)
        uniq   = deduplicar(company_jobs)
        depois = len(uniq)
        all_jobs.extend(uniq)
        print(f"  → {depois} vagas únicas ({antes - depois} duplicatas removidas)\n")

    # ─── SALVAR ──────────────────────────────────────────────────────────────
    ts          = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = OUTPUT_DIR / "vagas_faltantes.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Vagas novas coletadas : {len(all_jobs)}")
    print(f"  Salvo em             : {output_path}")
    print(f"{'='*60}")
    print(f"\nPróximo passo: rode etl_merge.py para juntar com vagas_todas_areas.json")

    counter = Counter(j.get("_meta_company","?") for j in all_jobs)
    print("\nResumo por empresa:")
    for name, count in sorted(counter.items(), key=lambda x: -x[1]):
        ok = "✓" if count >= 20 else "⚠ "
        print(f"  {ok} {name:<25} | {count} vagas")

    if erros:
        print(f"\n⚠  {len(erros)} erros:")
        for e in erros[:10]:
            print(f"  - {e}")


if __name__ == "__main__":
    run()