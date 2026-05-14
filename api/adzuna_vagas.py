"""

Coleta vagas de emprego no Brasil via Adzuna Developer API.
100% gratuito, oficial, sustentável — sem scraping, sem ToS violation.

COMO OBTER AS CREDENCIAIS:
    1. Acesse https://developer.adzuna.com/
    2. Clique em "Register" e crie uma conta gratuita
    3. Vá em "Dashboard" → "Your Apps" → "Create App"
    4. Copie o "App ID" e "App Key"
    5. Adicione no .env:
       ADZUNA_APP_ID=seu_app_id
       ADZUNA_APP_KEY=sua_app_key

ENDPOINTS UTILIZADOS:
    /jobs/br/search  → busca vagas com filtros
    /jobs/br/histogram → distribuição de salários por keyword

USO:
    python api/adzuna_vagas.py

SAÍDA:
    data/processed/adzuna_vagas_br.csv
"""

import os
import json
import time
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/br"

# ─── BUSCAS POR EMPRESA E ÁREA ────────────────────────────────────────────────
BUSCAS = [
    # C6 Bank
    {"empresa": "C6 Bank", "area": "tecnologia",  "what": "C6 Bank engenheiro software"},
    {"empresa": "C6 Bank", "area": "dados",        "what": "C6 Bank data engineer analyst"},
    {"empresa": "C6 Bank", "area": "negocios",     "what": "C6 Bank produto gerente"},
    {"empresa": "C6 Bank", "area": "operacoes",    "what": "C6 Bank operações analista"},
    {"empresa": "C6 Bank", "area": "corporativo",  "what": "C6 Bank juridico compliance RH"},

    # Nubank
    {"empresa": "Nubank",  "area": "tecnologia",  "what": "Nubank software engineer"},
    {"empresa": "Nubank",  "area": "dados",        "what": "Nubank data engineer scientist"},
    {"empresa": "Nubank",  "area": "negocios",     "what": "Nubank product manager"},

    # Itaú
    {"empresa": "Itaú",    "area": "tecnologia",  "what": "Itaú Unibanco engenheiro software"},
    {"empresa": "Itaú",    "area": "negocios",     "what": "Itaú Unibanco gerente produto"},
    {"empresa": "Itaú",    "area": "operacoes",    "what": "Itaú Unibanco operações analista"},

    # XP
    {"empresa": "XP",      "area": "tecnologia",  "what": "XP Investimentos engenheiro"},
    {"empresa": "XP",      "area": "negocios",     "what": "XP Investimentos assessor produto"},

    # Bradesco
    {"empresa": "Bradesco","area": "tecnologia",  "what": "Bradesco engenheiro software"},
    {"empresa": "Bradesco","area": "operacoes",    "what": "Bradesco operações analista"},

    # BTG
    {"empresa": "BTG",     "area": "negocios",     "what": "BTG Pactual analista investimentos"},
    {"empresa": "BTG",     "area": "tecnologia",  "what": "BTG Pactual engenheiro software"},
]

MAX_RESULTADOS_POR_BUSCA = 50  # Adzuna retorna até 50 por página


def buscar_vagas(what: str, empresa: str, area: str, page: int = 1) -> list:
    """
    Busca vagas no Adzuna Brasil.
    Parâmetros principais:
        what      = termos de busca (equivalente ao campo de busca)
        where     = localização (deixamos em branco para todo Brasil)
        results_per_page = até 50
        page      = paginação
    """
    url = f"{BASE_URL}/search/{page}"
    params = {
        "app_id":           ADZUNA_APP_ID,
        "app_key":          ADZUNA_APP_KEY,
        "results_per_page": MAX_RESULTADOS_POR_BUSCA,
        "what":             what,
        "content-type":     "application/json",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        vagas = data.get("results", [])
        total = data.get("count", 0)

        # Injetar metadados
        for vaga in vagas:
            vaga["_meta_empresa_busca"] = empresa
            vaga["_meta_area"]          = area
            vaga["_meta_query"]         = what

        return vagas, total

    except Exception as e:
        print(f"   ✗ Erro: {e}")
        return [], 0


def buscar_histograma_salarios(keyword: str) -> dict:
    """
    Retorna distribuição de salários para um keyword no Brasil.
    Útil para benchmark salarial por cargo.
    """
    url = f"{BASE_URL}/histogram"
    params = {
        "app_id":       ADZUNA_APP_ID,
        "app_key":      ADZUNA_APP_KEY,
        "what":         keyword,
        "content-type": "application/json",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"   ✗ Erro histograma {keyword}: {e}")
        return {}


def run():
    print("=" * 60)
    print("Adzuna API — Coleta de Vagas Brasil")
    print("=" * 60)

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("\n✗ Credenciais Adzuna não encontradas no .env")
        print("\nPasso a passo para obter as credenciais:")
        print("  1. Acesse https://developer.adzuna.com/")
        print("  2. Clique em 'Register' e crie uma conta gratuita")
        print("  3. Vá em 'Dashboard' → 'Your Apps' → 'Create App'")
        print("  4. Copie o App ID e App Key")
        print("  5. Adicione no .env:")
        print("     ADZUNA_APP_ID=seu_app_id")
        print("     ADZUNA_APP_KEY=sua_app_key")
        return

    todas_vagas = []
    total_buscas = len(BUSCAS)

    print(f"\nExecutando {total_buscas} buscas...\n")

    for i, busca in enumerate(BUSCAS, 1):
        empresa = busca["empresa"]
        area    = busca["area"]
        what    = busca["what"]

        print(f"[{i}/{total_buscas}] {empresa} | {area}")

        vagas, total = buscar_vagas(what, empresa, area)
        todas_vagas.extend(vagas)
        print(f"   → {len(vagas)} vagas (de {total} encontradas)")

        if i < total_buscas:
            time.sleep(1)  # respeitar rate limit

    # ─── SALVAR ──────────────────────────────────────────────────────────────
    if todas_vagas:
        df = pd.DataFrame(todas_vagas)

        # Normalizar campos principais
        campos_uteis = [
            "_meta_empresa_busca", "_meta_area", "_meta_query",
            "id", "title", "description", "company",
            "location", "salary_min", "salary_max",
            "created", "contract_type", "contract_time",
            "redirect_url", "adref",
        ]
        # Filtrar apenas colunas que existem
        campos_existentes = [c for c in campos_uteis if c in df.columns]
        df_clean = df[campos_existentes].copy()

        # Extrair nome da empresa e localização (são objetos aninhados)
        if "company" in df.columns:
            df_clean["company_name"] = df["company"].apply(
                lambda x: x.get("display_name", "") if isinstance(x, dict) else str(x)
            )
        if "location" in df.columns:
            df_clean["location_name"] = df["location"].apply(
                lambda x: x.get("display_name", "") if isinstance(x, dict) else str(x)
            )

        output_path = OUTPUT_DIR / "adzuna_vagas_br.csv"
        df_clean.to_csv(output_path, index=False, encoding="utf-8-sig")

        print(f"\n{'='*55}")
        print(f"✓ Total : {len(df_clean)} vagas")
        print(f"  Salvo : {output_path}")
        print(f"{'='*55}\n")

        from collections import Counter
        counter = Counter(
            (j.get("_meta_empresa_busca", "?"), j.get("_meta_area", "?"))
            for j in todas_vagas
        )
        print("Resumo por empresa + área:")
        for (emp, area), count in sorted(counter.items()):
            print(f"  {emp:<20} | {area:<12} | {count} vagas")

        # Bonus: buscar histograma de salários para cargos tech
        print("\nBuscando benchmarks salariais...")
        salarios = {}
        for cargo in ["data engineer Brasil", "software engineer Brasil", "product manager Brasil"]:
            hist = buscar_histograma_salarios(cargo)
            if hist:
                salarios[cargo] = hist
            time.sleep(1)

        if salarios:
            with open(OUTPUT_DIR / "adzuna_salarios_hist.json", "w", encoding="utf-8") as f:
                json.dump(salarios, f, ensure_ascii=False, indent=2)
            print(f"✓ Histogramas salariais salvos em data/processed/adzuna_salarios_hist.json")

    else:
        print("✗ Nenhuma vaga coletada.")


if __name__ == "__main__":
    run()