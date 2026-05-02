"""
scraping_vagas.py
=================
Coleta vagas do LinkedIn por empresa + área funcional.
Estratégia: múltiplas URLs por empresa (uma por área) para maximizar cobertura.

Actor: curious_coder/linkedin-jobs-scraper

LÓGICA:
    Em vez de 1 URL por empresa com limite de 200 vagas,
    usamos N URLs por empresa (uma por área funcional).
    Cada área retorna até MAX_PER_SEARCH vagas.
    Total possível: 8 empresas × 8 áreas × 50 vagas = ~3.200 vagas

DEPLOY SEMANAL:
    Adicione ao cron (Linux/Mac):
        0 8 * * 1 cd /path/to/project && python data/apify/scraping/vagas_linkedin.py
    
    Ou GitHub Actions (ver README para configuração).

USO:
    python data/apify/scraping/vagas_linkedin.py
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

ACTOR_ID = "curious_coder/linkedin-jobs-scraper"

# Máximo de vagas por busca (empresa + área)
# 50 é o sweet spot — mais que isso o actor fica lento e pode falhar
MAX_PER_SEARCH = 50

# Filtro de tempo — últimos 30 dias para coleta semanal
# r604800  = última semana  (para runs semanais em produção)
# r2592000 = últimos 30 dias (para coleta inicial completa)
TIME_FILTER = "r2592000"

# ─── EMPRESAS ────────────────────────────────────────────────────────────────
# f_C: IDs verificados manualmente na página de vagas de cada empresa
# Use múltiplos IDs separados por %2C para incluir subsidiárias

COMPANIES = [
    {
        "name": "C6 Bank",
        "slug": "c6_bank",
        "f_C":  "10185987",
    },
    {
        "name": "Nubank",
        "slug": "nubank",
        "f_C":  "3767529",
    },
    {
        "name": "Itaú Unibanco",
        "slug": "itau",
        "f_C":  "333329",
    },
    {
        "name": "XP Investimentos",
        "slug": "xp",
        "f_C":  "11794476%2C14031303%2C2304919%2C144288%2C2540096",
    },
    {
        "name": "Bradesco",
        "slug": "bradesco",
        "f_C":  "162778",
    },
    {
        "name": "iFood",
        "slug": "ifood",
        "f_C":  "247645%2C101015933",
    },
    {
        "name": "BTG Pactual",
        "slug": "btg",
        "f_C":  "654090%2C53185306%2C71627692%2C3188881%2C11767688%2C22953308",
    },
    {
        "name": "Santander Brasil",
        "slug": "santander",
        "f_C":  "434631%2C66197178%2C83543692",
    },
]

# ─── ÁREAS FUNCIONAIS ────────────────────────────────────────────────────────
# f_CF: códigos de função do LinkedIn
# Cobrem as 4 áreas do case: Tecnologia, Negócios, Operações, Corporativo

AREAS = [
    # Tecnologia
    {"code": "4",  "nome": "tecnologia",  "label": "Engenharia"},
    {"code": "8",  "nome": "tecnologia",  "label": "TI"},
    {"code": "2",  "nome": "dados",       "label": "Dados e Analytics"},

    # Negócios
    {"code": "9",  "nome": "negocios",    "label": "Marketing"},
    {"code": "13", "nome": "negocios",    "label": "Vendas"},
    {"code": "10", "nome": "negocios",    "label": "Produto"},

    # Operações
    {"code": "14", "nome": "operacoes",   "label": "Operações"},
    {"code": "15", "nome": "operacoes",   "label": "Suporte"},

    # Corporativo
    {"code": "3",  "nome": "corporativo", "label": "Finanças"},
    {"code": "26", "nome": "corporativo", "label": "Jurídico"},
    {"code": "7",  "nome": "corporativo", "label": "RH"},
    {"code": "21", "nome": "corporativo", "label": "Administrativo"},
]


def build_url(f_C: str, f_CF: str) -> str:
    """Constrói URL de busca do LinkedIn com filtros de empresa e área."""
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?f_C={f_C}"
        f"&f_CF={f_CF}"
        "&geoId=106057199"       # Brasil
        "&keywords="
        f"&f_TPR={TIME_FILTER}"
    )


def deduplicar(jobs: list) -> list:
    """Remove vagas duplicadas pelo jobId do LinkedIn."""
    seen = set()
    unique = []
    for job in jobs:
        job_id = job.get("jobId") or job.get("id") or job.get("url", "")
        if job_id and job_id not in seen:
            seen.add(job_id)
            unique.append(job)
        elif not job_id:
            unique.append(job)
    return unique


def run_scraping():
    if not APIFY_TOKEN:
        raise ValueError("APIFY_TOKEN não encontrado no .env")

    client   = ApifyClient(APIFY_TOKEN)
    all_jobs = []
    erros    = []

    total_searches = len(COMPANIES) * len(AREAS)
    current = 0

    print("=" * 60)
    print("LinkedIn Jobs Scraper — Coleta por Empresa + Área")
    print(f"Empresas: {len(COMPANIES)} | Áreas: {len(AREAS)}")
    print(f"Total de buscas: {total_searches}")
    print(f"Máximo estimado: {total_searches * MAX_PER_SEARCH} vagas")
    print("=" * 60)

    for company in COMPANIES:
        company_jobs = []
        print(f"\n[{company['name']}]")

        for area in AREAS:
            current += 1
            url = build_url(company["f_C"], area["code"])

            run_input = {
                "urls":            [url],
                "maxResults":      MAX_PER_SEARCH,
                "parseJobDetails": True,
            }

            try:
                run   = client.actor(ACTOR_ID).call(run_input=run_input)
                items = list(
                    client.dataset(run["defaultDatasetId"]).iterate_items()
                )

                for item in items:
                    item["_meta_company"]    = company["name"]
                    item["_meta_slug"]       = company["slug"]
                    item["_meta_area"]       = area["nome"]
                    item["_meta_area_label"] = area["label"]

                company_jobs.extend(items)
                print(f"  {area['label']:<20} → {len(items)} vagas")

            except Exception as e:
                erros.append(f"{company['name']} / {area['label']}: {e}")
                print(f"  {area['label']:<20} → ✗ {e}")

            # Pausa entre requests para não sobrecarregar
            time.sleep(1.5)

        # Deduplicar por empresa antes de adicionar ao total
        antes = len(company_jobs)
        company_jobs = deduplicar(company_jobs)
        depois = len(company_jobs)
        duplicatas = antes - depois

        all_jobs.extend(company_jobs)
        print(f"  → {depois} vagas únicas ({duplicatas} duplicatas removidas)")

    # ─── DEDUPLICAÇÃO GLOBAL ─────────────────────────────────────────────────
    total_antes = len(all_jobs)
    all_jobs = deduplicar(all_jobs)
    total_depois = len(all_jobs)

    # ─── SALVAR ──────────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = OUTPUT_DIR / f"vagas_todas_areas.json"
    output_path_ts = OUTPUT_DIR / f"vagas_{timestamp}.json"  # backup datado

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    with open(output_path_ts, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Total bruto        : {total_antes}")
    print(f"✓ Total deduplicado  : {total_depois}")
    print(f"  Arquivo principal  : {output_path}")
    print(f"  Backup datado      : {output_path_ts}")
    print(f"{'='*60}\n")

    # Resumo por empresa + área
    counter_empresa = Counter(j.get("_meta_company", "?") for j in all_jobs)
    counter_area    = Counter(
        (j.get("_meta_company", "?"), j.get("_meta_area", "?"))
        for j in all_jobs
    )

    print("Resumo por empresa:")
    for name, count in sorted(counter_empresa.items()):
        ok   = "✓" if count >= 20 else "⚠ "
        note = "" if count >= 20 else " — baixo"
        print(f"  {ok} {name:<25} | {count} vagas{note}")

    print("\nResumo por empresa + área (top resultados):")
    for (emp, area), count in sorted(counter_area.items(), key=lambda x: -x[1])[:20]:
        print(f"  {emp:<22} | {area:<12} | {count}")

    if erros:
        print(f"\n⚠  {len(erros)} erros durante a coleta:")
        for e in erros:
            print(f"  - {e}")


if __name__ == "__main__":
    run_scraping()