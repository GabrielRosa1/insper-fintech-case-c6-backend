"""
etl_vagas.py
============
ETL das vagas do LinkedIn para a base de Market Intelligence.

INPUTS:
    data/apify/scraping_linkedin_1.json  (C6, Nubank, Itaú)
    data/apify/scraping_linkedin_2.json  (XP, Bradesco)
    data/apify/scraping_linkedin_3.json  (iFood, BTG, Santander)

OUTPUTS:
    data/processed/vagas_market_intelligence.csv  ← base principal
    data/processed/vagas_skills.csv               ← skills extraídas
    data/processed/vagas_resumo.csv               ← agregado por empresa+área

USO:
    python etl/etl_vagas.py
"""

import re
import json
import pandas as pd
from pathlib import Path
from collections import Counter

# ─── CAMINHOS ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.parent
INPUT_FILES = [
    BASE_DIR / "data/apify/scraping_linkedin_1.json",
    BASE_DIR / "data/apify/scraping_linkedin_2.json",
    BASE_DIR / "data/apify/scraping_linkedin_3.json",
]
OUTPUT_DIR  = BASE_DIR / "data/processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── SKILLS PARA EXTRAÇÃO (via NLP simples em descriptionText) ───────────────
SKILLS_MAP = {
    # Linguagens
    "python":        ["python"],
    "java":          ["java", "java 8", "java 11", "java 17"],
    "kotlin":        ["kotlin"],
    "scala":         ["scala"],
    "golang":        ["golang", "go lang", " go "],
    "javascript":    ["javascript", "js", "node.js", "nodejs"],
    "typescript":    ["typescript", " ts "],
    "c#":            ["c#", "csharp", "c sharp"],
    "c++":           ["c++", "c plus plus"],
    "ruby":          ["ruby on rails", "ruby"],
    "swift":         ["swift"],
    "r_lang":        [" r ", "linguagem r", "rstudio"],
    "sql":           ["sql", "mysql", "postgresql", "postgres", "oracle sql"],

    # Dados & BI
    "spark":         ["apache spark", "pyspark", "spark"],
    "kafka":         ["apache kafka", "kafka"],
    "airflow":       ["apache airflow", "airflow"],
    "dbt":           ["dbt", "data build tool"],
    "databricks":    ["databricks"],
    "bigquery":      ["bigquery", "big query"],
    "pandas":        ["pandas"],
    "scikit_learn":  ["scikit-learn", "sklearn"],
    "tensorflow":    ["tensorflow"],
    "pytorch":       ["pytorch"],
    "power_bi":      ["power bi", "powerbi"],
    "tableau":       ["tableau"],
    "looker":        ["looker"],

    # Cloud
    "aws":           ["aws", "amazon web services", "ec2", "s3 ", "lambda"],
    "gcp":           ["gcp", "google cloud", "google cloud platform"],
    "azure":         ["azure", "microsoft azure"],

    # DevOps / Infra
    "docker":        ["docker"],
    "kubernetes":    ["kubernetes", "k8s"],
    "terraform":     ["terraform"],
    "git":           ["git ", "github", "gitlab", "bitbucket"],
    "ci_cd":         ["ci/cd", "cicd", "jenkins", "github actions", "gitlab ci"],

    # Arquitetura
    "microservices": ["microservice", "microsserviço", "microsserviços"],
    "api_rest":      ["api rest", "restful", "rest api"],
    "graphql":       ["graphql"],
    "event_driven":  ["event-driven", "event driven", "event sourcing"],

    # Metodologias
    "agile":         ["agile", "scrum", "kanban", "safe "],
    "machine_learning": ["machine learning", "ml ", "aprendizado de máquina"],
    "deep_learning": ["deep learning"],
    "nlp":           ["nlp", "natural language processing", "processamento de linguagem"],

    # Finanças / Negócios
    "cfa":           ["cfa"],
    "cfp":           ["cfp"],
    "cpa":           ["cpa-"],
    "excel":         ["excel", "vba"],
    "salesforce":    ["salesforce"],
    "sap":           ["sap "],
    "power_apps":    ["power apps", "powerapps"],
}

# ─── MAPEAMENTO DE ÁREA POR jobFunction ──────────────────────────────────────
AREA_MAP = {
    "tecnologia": [
        "engineering and information technology",
        "information technology",
        "design, art/creative, and information technology",
        "engineering",
        "information technology, engineering",
        "information technology and engineering",
        "project management and information technology",
        "other and information technology",
        "other, information technology, and management",
        "information technology, business development, and project management",
        "information technology, project management, and business development",
    ],
    "dados": [
        "research, analyst, and information technology",
        "analyst",
    ],
    "negocios": [
        "sales and business development",
        "business development and sales",
        "product management and marketing",
        "product management",
        "marketing, public relations, and writing/editing",
        "general business, management, and business development",
        "strategy/planning and project management",
        "consulting, business development, and strategy/planning",
        "consulting, information technology, and sales",
        "sales and management",
        "customer service, consulting, and sales",
        "strategy/planning",
        "consulting",
    ],
    "operacoes": [
        "management and manufacturing",
        "administrative",
        "customer service",
        "health care provider",
    ],
    "corporativo": [
        "finance and sales",
        "finance",
        "accounting/auditing and finance",
        "finance and accounting/auditing",
        "finance and customer service",
        "finance and general business",
        "finance, product management, and strategy/planning",
        "finance and information technology",
        "human resources",
        "legal",
        "education and training",
    ],
}

# ─── MAPEAMENTO DE SENIORIDADE ────────────────────────────────────────────────
SENIORITY_LI = {
    "internship":       "estagio",
    "entry level":      "junior",
    "associate":        "junior",
    "mid-senior level": "senior",
    "director":         "diretor",
    "executive":        "executivo",
    "not applicable":   None,
}

SENIORITY_TITLE = [
    (["estagi", "intern"],                "estagio"),
    (["júnior", "junior", " jr ", " jr."], "junior"),
    (["pleno", " pl ", " pl."],            "pleno"),
    (["sênior", "senior", " sr ", " sr.", "sênior", "ii", "iii"],  "senior"),
    (["especialista", "specialist", "lead", "lider", "líder"],     "especialista"),
    (["coordenad", "coordinat"],           "coordenador"),
    (["gerente", "manager"],               "gerente"),
    (["diretor", "director"],              "diretor"),
    (["vp ", "vice-president", "vice president"], "vp"),
    (["cto", "ceo", "cfo", "coo", " c-level"], "c-level"),
]

# ─── MAPEAMENTO DE MODELO DE TRABALHO ────────────────────────────────────────
def extract_work_model(row) -> str:
    wt = row.get("workplaceTypes", [])
    if isinstance(wt, list) and wt:
        wt_lower = [w.lower() for w in wt]
        if "remote" in wt_lower:         return "remoto"
        if "hybrid" in wt_lower:         return "hibrido"
        if "on-site" in wt_lower:        return "presencial"
    # fallback: location
    loc = str(row.get("location", "")).lower()
    if "remote" in loc or "remoto" in loc: return "remoto"
    if "hybrid" in loc or "híbrido" in loc: return "hibrido"
    if "on-site" in loc or "presencial" in loc: return "presencial"
    return "nao_informado"


# ─── FUNÇÕES DE EXTRAÇÃO ──────────────────────────────────────────────────────
def classify_area(job_function: str, meta_area: str) -> str:
    """Classifica área com base no jobFunction do LinkedIn ou _meta_area do scraping."""
    jf = str(job_function).lower().strip()
    for area, keywords in AREA_MAP.items():
        if jf in keywords:
            return area
    # fallback: _meta_area do script de scraping
    if meta_area and meta_area not in ("None", "nan", ""):
        return str(meta_area)
    return "outros"


def classify_seniority(row) -> str:
    """Classifica senioridade pelo campo do LinkedIn ou pelo título."""
    # 1. Tentar campo seniorityLevel do LinkedIn
    li = str(row.get("seniorityLevel", "")).lower().strip()
    if li in SENIORITY_LI and SENIORITY_LI[li]:
        return SENIORITY_LI[li]

    # 2. Inferir pelo título
    title = str(row.get("title", "")).lower()
    for keywords, level in SENIORITY_TITLE:
        if any(kw in title for kw in keywords):
            return level

    return "nao_classificado"


def extract_skills(text: str) -> dict:
    """Extrai skills do descriptionText. Retorna dict skill→bool."""
    if not text:
        return {skill: False for skill in SKILLS_MAP}
    text_lower = text.lower()
    result = {}
    for skill, patterns in SKILLS_MAP.items():
        result[skill] = any(p in text_lower for p in patterns)
    return result


def extract_location(location_str: str):
    """Extrai cidade e UF/estado da string de location."""
    if not location_str:
        return None, None
    # Remove modelo de trabalho do final
    loc = re.sub(r'\s*\(.*?\)\s*$', '', location_str).strip()
    parts = [p.strip() for p in loc.split(",")]
    cidade = parts[0] if parts else None
    estado = parts[1] if len(parts) > 1 else None
    return cidade, estado


# ─── ETL PRINCIPAL ────────────────────────────────────────────────────────────
def run():
    print("=" * 55)
    print("ETL — LinkedIn Jobs → Market Intelligence")
    print("=" * 55)

    # 1. Carregar todos os JSONs
    all_jobs = []
    for path in INPUT_FILES:
        if not path.exists():
            print(f"⚠  {path.name} não encontrado — pulando")
            continue
        with open(path, encoding="utf-8") as f:
            jobs = json.load(f)
        print(f"✓ {path.name}: {len(jobs)} vagas")
        all_jobs.extend(jobs)

    print(f"\nTotal bruto: {len(all_jobs)} vagas")

    # 2. Deduplicar por id
    seen, unique = set(), []
    for job in all_jobs:
        jid = str(job.get("id", ""))
        if jid and jid not in seen:
            seen.add(jid)
            unique.append(job)
        elif not jid:
            unique.append(job)
    print(f"Total deduplicado: {len(unique)} vagas")

    # 3. Transformar em DataFrame
    records = []
    skills_records = []

    for job in unique:
        jid      = str(job.get("id", ""))
        empresa  = job.get("companyName") or job.get("_meta_company", "")
        titulo   = job.get("title", "")
        desc     = job.get("descriptionText", "")
        location = job.get("location", "")
        cidade, estado = extract_location(location)

        area       = classify_area(job.get("jobFunction",""), job.get("_meta_area",""))
        senio      = classify_seniority(job)
        work_model = extract_work_model(job)

        # Data de publicação
        posted = job.get("postedAt", "")
        if posted:
            posted = posted[:10]  # YYYY-MM-DD

        # Candidatos
        n_cands = job.get("applicantsCount")
        try:
            n_cands = int(n_cands) if n_cands else None
        except (ValueError, TypeError):
            n_cands = None

        record = {
            "id":               jid,
            "empresa":          empresa,
            "titulo":           titulo,
            "area":             area,
            "senioridade":      senio,
            "modelo_trabalho":  work_model,
            "cidade":           cidade,
            "estado":           estado,
            "pais":             job.get("country", "BR"),
            "data_publicacao":  posted,
            "n_candidatos":     n_cands,
            "emprego_tipo":     job.get("employmentType", ""),
            "seniority_li":     job.get("seniorityLevel", ""),
            "job_function_li":  job.get("jobFunction", ""),
            "industries":       job.get("industries", ""),
            "easy_apply":       job.get("easyApply", False),
            "tem_salario":      bool(job.get("salary")),
            "link":             job.get("link", ""),
            "apply_url":        job.get("applyUrl", ""),
            "n_funcionarios_empresa": job.get("companyEmployeesCount"),
        }
        records.append(record)

        # Skills
        skills = extract_skills(desc)
        skill_record = {"id": jid, "empresa": empresa, "area": area}
        skill_record.update(skills)
        skills_records.append(skill_record)

    df       = pd.DataFrame(records)
    df_skills = pd.DataFrame(skills_records)

    # 4. Limpeza
    df["empresa"] = df["empresa"].str.strip()
    df["titulo"]  = df["titulo"].str.strip()

    # 5. Salvar base principal
    out_main = OUTPUT_DIR / "vagas_market_intelligence.csv"
    df.to_csv(out_main, index=False, encoding="utf-8-sig")
    print(f"\n✓ Base principal salva: {out_main}")
    print(f"  Shape: {df.shape}")

    # 6. Salvar skills
    out_skills = OUTPUT_DIR / "vagas_skills.csv"
    df_skills.to_csv(out_skills, index=False, encoding="utf-8-sig")
    print(f"✓ Skills salvas: {out_skills}")

    # 7. Gerar resumo agregado
    resumo = (
        df.groupby(["empresa", "area"])
        .agg(
            total_vagas        = ("id", "count"),
            pct_remoto         = ("modelo_trabalho", lambda x: (x == "remoto").mean()),
            pct_hibrido        = ("modelo_trabalho", lambda x: (x == "hibrido").mean()),
            pct_presencial     = ("modelo_trabalho", lambda x: (x == "presencial").mean()),
            pct_senior         = ("senioridade", lambda x: (x == "senior").mean()),
            pct_junior         = ("senioridade", lambda x: (x == "junior").mean()),
            media_candidatos   = ("n_candidatos", "mean"),
        )
        .round(3)
        .reset_index()
    )

    out_resumo = OUTPUT_DIR / "vagas_resumo.csv"
    resumo.to_csv(out_resumo, index=False, encoding="utf-8-sig")
    print(f"✓ Resumo salvo: {out_resumo}")

    # 8. Ranking de skills por empresa
    skill_cols = list(SKILLS_MAP.keys())
    skill_rank = (
        df_skills.groupby("empresa")[skill_cols]
        .mean()
        .round(3)
        .reset_index()
    )
    out_rank = OUTPUT_DIR / "vagas_skills_por_empresa.csv"
    skill_rank.to_csv(out_rank, index=False, encoding="utf-8-sig")
    print(f"✓ Ranking de skills salvo: {out_rank}")

    # ─── PREVIEW DOS RESULTADOS ──────────────────────────────────────────────
    print(f"\n{'='*55}")
    print("PREVIEW — Vagas por empresa + área")
    print(f"{'='*55}")
    pivot = df.groupby(["empresa","area"]).size().unstack(fill_value=0)
    print(pivot.to_string())

    print(f"\n{'='*55}")
    print("PREVIEW — Modelo de trabalho por empresa")
    print(f"{'='*55}")
    wm = df.groupby(["empresa","modelo_trabalho"]).size().unstack(fill_value=0)
    print(wm.to_string())

    print(f"\n{'='*55}")
    print("PREVIEW — Top 10 skills mais demandadas (geral)")
    print(f"{'='*55}")
    skill_totals = df_skills[skill_cols].mean().sort_values(ascending=False).head(10)
    for skill, pct in skill_totals.items():
        bar = "█" * int(pct * 30)
        print(f"  {skill:<20} {pct*100:>5.1f}%  {bar}")

    print(f"\n{'='*55}")
    print("PREVIEW — Senioridade por empresa")
    print(f"{'='*55}")
    sen = df.groupby(["empresa","senioridade"]).size().unstack(fill_value=0)
    print(sen.to_string())

    print(f"\n\nArquivos gerados em: {OUTPUT_DIR}")


if __name__ == "__main__":
    run()