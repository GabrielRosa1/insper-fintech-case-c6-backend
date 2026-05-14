"""

Coleta vagas tech brasileiras via GitHub Issues (repositórios de vagas).
100% gratuito, oficial, tempo real — sem scraping.

REPOSITÓRIOS MONITORADOS:
    frontendbr/vagas     — Frontend (15k+ stars)
    backend-br/vagas     — Backend
    react-brasil/vagas   — React/Frontend
    qa-brasil/vagas      — QA/Testes
    androiddevbr/vagas   — Android
    iosdevbr/vagas       — iOS

AUTENTICAÇÃO (opcional mas recomendado):
    Sem token: 60 req/hora
    Com token: 5.000 req/hora
    
    Para gerar um token:
    1. GitHub → Settings → Developer Settings
    2. Personal Access Tokens → Tokens (classic)
    3. New token → escopo: public_repo (read only)
    4. Adicione no .env: GITHUB_TOKEN=ghp_seu_token

USO:
    python api/github_vagas.py

SAÍDA:
    data/processed/github_vagas_tech.csv
"""

import os
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://api.github.com"

# Headers da requisição
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Repositórios de vagas
REPOS = [
    {"repo": "frontendbr/vagas",    "area": "frontend"},
    {"repo": "backend-br/vagas",    "area": "backend"},
    {"repo": "react-brasil/vagas",  "area": "react"},
    {"repo": "qa-brasil/vagas",     "area": "qa"},
    {"repo": "androiddevbr/vagas",  "area": "mobile_android"},
    {"repo": "iosdevbr/vagas",      "area": "mobile_ios"},
]

# Buscar vagas dos últimos N dias
DIAS_ATRAS = 90
MAX_POR_REPO = 200


def buscar_issues(repo: str, area: str, dias: int = 90) -> list:
    """
    Busca issues abertas de um repositório de vagas.
    Cada issue = uma vaga publicada.
    """
    desde = (datetime.utcnow() - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"{BASE_URL}/repos/{repo}/issues"

    todas_issues = []
    page = 1

    while len(todas_issues) < MAX_POR_REPO:
        params = {
            "state":     "open",
            "sort":      "created",
            "direction": "desc",
            "since":     desde,
            "per_page":  100,
            "page":      page,
        }

        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=30)

            # Verificar rate limit
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
            if remaining < 5:
                reset_time = int(resp.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset_time - int(time.time()), 0) + 5
                print(f"   ⚠  Rate limit próximo — aguardando {wait}s...")
                time.sleep(wait)

            resp.raise_for_status()
            issues = resp.json()

            if not issues:
                break

            # Filtrar apenas issues (não pull requests)
            issues_filtradas = [i for i in issues if "pull_request" not in i]

            for issue in issues_filtradas:
                issue["_meta_repo"] = repo
                issue["_meta_area"] = area

            todas_issues.extend(issues_filtradas)
            page += 1

            if len(issues) < 100:
                break  # última página

        except Exception as e:
            print(f"   ✗ Erro em {repo}: {e}")
            break

    return todas_issues[:MAX_POR_REPO]


def extrair_campos(issue: dict) -> dict:
    """
    Extrai campos relevantes de uma issue de vaga.
    As vagas geralmente têm labels como: CLT, PJ, Pleno, Sênior, Remoto, etc.
    """
    labels = [label["name"] for label in issue.get("labels", [])]

    return {
        "id":              issue.get("number"),
        "titulo":          issue.get("title", ""),
        "descricao":       issue.get("body", "")[:500] if issue.get("body") else "",
        "url":             issue.get("html_url", ""),
        "data_criacao":    issue.get("created_at", ""),
        "data_atualizacao":issue.get("updated_at", ""),
        "labels":          ", ".join(labels),
        "tem_clt":         "CLT" in labels,
        "tem_pj":          "PJ" in labels,
        "tem_remoto":      any(l in ["Remoto", "Remote", "remoto"] for l in labels),
        "tem_hibrido":     any(l in ["Híbrido", "Hibrido", "Hybrid"] for l in labels),
        "tem_presencial":  any(l in ["Presencial", "On-site"] for l in labels),
        "nivel_junior":    any(l in ["Júnior", "Junior", "Estágio", "Estagio"] for l in labels),
        "nivel_pleno":     any(l in ["Pleno"] for l in labels),
        "nivel_senior":    any(l in ["Sênior", "Senior", "Especialista"] for l in labels),
        "repo":            issue.get("_meta_repo", ""),
        "area":            issue.get("_meta_area", ""),
    }


def run():
    print("=" * 60)
    print("GitHub Vagas — Coleta de Vagas Tech Brasil")
    print("=" * 60)

    if not GITHUB_TOKEN:
        print("\n⚠  GITHUB_TOKEN não configurado — usando limite de 60 req/hora")
        print("   Para mais velocidade, adicione GITHUB_TOKEN no .env")
    else:
        print(f"\n✓ Token GitHub configurado — limite: 5.000 req/hora")

    todas_vagas = []
    total_repos = len(REPOS)

    print(f"\nColetando vagas dos últimos {DIAS_ATRAS} dias de {total_repos} repositórios...\n")

    for i, repo_info in enumerate(REPOS, 1):
        repo = repo_info["repo"]
        area = repo_info["area"]

        print(f"[{i}/{total_repos}] {repo} | {area}")
        issues = buscar_issues(repo, area, DIAS_ATRAS)
        vagas  = [extrair_campos(issue) for issue in issues]
        todas_vagas.extend(vagas)
        print(f"   → {len(vagas)} vagas coletadas")

        time.sleep(0.5)

    # ─── SALVAR ──────────────────────────────────────────────────────────────
    if todas_vagas:
        df = pd.DataFrame(todas_vagas)
        output_path = OUTPUT_DIR / "github_vagas_tech.csv"
        df.to_csv(output_path, index=False, encoding="utf-8-sig")

        print(f"\n{'='*55}")
        print(f"✓ Total : {len(df)} vagas")
        print(f"  Salvo : {output_path}")
        print(f"{'='*55}\n")

        print("Resumo por área:")
        print(df.groupby("area").size().to_string())

        print("\nDistribuição por modelo de trabalho:")
        print(f"  Remoto    : {df['tem_remoto'].sum()}")
        print(f"  Híbrido   : {df['tem_hibrido'].sum()}")
        print(f"  Presencial: {df['tem_presencial'].sum()}")
        print(f"  CLT       : {df['tem_clt'].sum()}")
        print(f"  PJ        : {df['tem_pj'].sum()}")

    else:
        print("✗ Nenhuma vaga coletada.")


if __name__ == "__main__":
    run()