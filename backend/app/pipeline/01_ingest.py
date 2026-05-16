"""
Pipeline Step 01 — Ingestão de dados brutos

Carrega para o banco:
  • Reviews: data/raw/c6bank.json + data/raw/nubank.json
  • Vagas:   data/raw/vagas_market_intelligence.csv
             data/raw/vagas_resumo.csv
             data/raw/vagas_skills_por_empresa.csv
             data/raw/vagas_skills.csv

Idempotente: detecta duplicatas por source_file+empresa antes de inserir.

"""

import json
import os
import sys
import pandas as pd
from datetime import datetime, date
from pathlib import Path
from sqlalchemy import text
from tqdm import tqdm

# Garante que o diretório raiz do projeto está no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session
from app.config import get_settings

settings = get_settings()

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR  = BASE_DIR / "data" / "raw"

REVIEW_FILES = {
    "c6_bank": RAW_DIR / "c6bank.json",
    "nubank":  RAW_DIR / "nubank.json",
}

JOBS_MARKET    = RAW_DIR / "vagas_market_intelligence.csv"
JOBS_RESUMO    = RAW_DIR / "vagas_resumo.csv"
JOBS_SKILLS    = RAW_DIR / "vagas_skills.csv"
JOBS_SKILLS_CO = RAW_DIR / "vagas_skills_por_empresa.csv"

# Skills disponíveis nos CSVs (em ordem)
SKILL_COLS = [
    "python","java","kotlin","scala","golang","javascript","typescript",
    "c#","c++","ruby","swift","r_lang","sql","spark","kafka","airflow",
    "dbt","databricks","bigquery","pandas","scikit_learn","tensorflow",
    "pytorch","power_bi","tableau","looker","aws","gcp","azure","docker",
    "kubernetes","terraform","git","ci_cd","microservices","api_rest",
    "graphql","event_driven","agile","machine_learning","deep_learning",
    "nlp","cfa","cfp","cpa","excel","salesforce","sap","power_apps",
]

# Palavras-chave que indicam review de evento (não de experiência de trabalho)
EVENT_KEYWORDS = [
    "foto", "linkedin", "sorvete", "campanha",
    "fotos profissionais", "ação foto", "modelando",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_date(val) -> date | None:
    if not val:
        return None
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_bool(val) -> bool | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "sim")
    return bool(val)


def is_event_review(review: dict) -> bool:
    """Detecta reviews de eventos internos (ex: campanha de fotos LinkedIn C6)."""
    texto = " ".join([
        str(review.get("titulo_review") or ""),
        str(review.get("pros") or ""),
    ]).lower()
    return any(kw in texto for kw in EVENT_KEYWORDS)


def get_company_map(session) -> dict[str, int]:
    """Retorna {slug: id} para todas as companies no banco."""
    rows = session.execute(text("SELECT slug, id FROM companies")).fetchall()
    return {row[0]: row[1] for row in rows}


def normalize_work_model(modelo: str | None) -> str:
    if not modelo:
        return "unknown"
    m = str(modelo).lower()
    if "remoto" in m or "remote" in m:
        return "remote"
    if "híbrido" in m or "hibrido" in m or "hybrid" in m:
        return "hybrid"
    if "presencial" in m or "on-site" in m or "on_site" in m:
        return "on_site"
    return "unknown"


def slug_from_empresa(nome: str) -> str | None:
    """Mapeia nome de empresa para slug da tabela companies."""
    mapa = {
        "C6 Bank":    "c6_bank",
        "C6Bank":     "c6_bank",
        "Nubank":     "nubank",
        "Nu":         "nubank",
    }
    return mapa.get(nome)


# ── Reviews ──────────────────────────────────────────────────────────────────

def ingest_reviews(session, company_map: dict) -> dict:
    stats = {"inserted": 0, "skipped_no_company": 0, "skipped_incomplete": 0,
             "skipped_duplicate": 0, "skipped_event": 0}

    for company_slug, filepath in REVIEW_FILES.items():
        if not filepath.exists():
            print(f"  ⚠️  Arquivo não encontrado: {filepath}")
            continue

        company_id = company_map.get(company_slug)
        if not company_id:
            print(f"  ❌ Company '{company_slug}' não encontrada no banco.")
            stats["skipped_no_company"] += 1
            continue

        with open(filepath, encoding="utf-8") as f:
            raw_data = json.load(f)

        print(f"\n  📂 {filepath.name} — {len(raw_data)} registros brutos")

        # Busca source_files já inseridos para esta empresa (idempotência)
        existing = set(
            row[0] for row in session.execute(
                text("SELECT source_file FROM reviews WHERE company_id = :cid"),
                {"cid": company_id},
            ).fetchall()
        )

        batch = []
        for r in tqdm(raw_data, desc=f"    Preparando {company_slug}", leave=False):
            # Pula registros sem review completa
            if r.get("_no_complete_reviews"):
                stats["skipped_incomplete"] += 1
                continue

            # Pula se não tem nenhum texto útil
            if not any([r.get("pros"), r.get("contras"), r.get("titulo_review")]):
                stats["skipped_incomplete"] += 1
                continue

            source_file = r.get("_source_file", "")

            # Idempotência por source_file
            if source_file in existing:
                stats["skipped_duplicate"] += 1
                continue

            # Detecta review de evento
            is_event = is_event_review(r)
            if is_event:
                stats["skipped_event"] += 1

            # Calcula quality_score simples (0-1)
            fields_filled = sum([
                bool(r.get("pros")),
                bool(r.get("contras")),
                bool(r.get("titulo_review")),
                bool(r.get("conselho_presidencia")),
                bool(r.get("cargo")),
                bool(r.get("data_review")),
                bool(r.get("avaliacao_geral")),
            ])
            quality = round(fields_filled / 7, 2)

            batch.append({
                "company_id":           company_id,
                "cargo":                r.get("cargo"),
                "localizacao":          r.get("localizacao"),
                "data_review":          parse_date(r.get("data_review")),
                "status_funcionario":   r.get("status_funcionario"),
                "tempo_empresa":        r.get("tempo_empresa"),
                "avaliacao_geral":      r.get("avaliacao_geral"),
                "recomendaria":         parse_bool(r.get("recomendaria")),
                "aprovacao_ceo":        parse_bool(r.get("aprovacao_ceo")),
                "perspectiva_negocio":  parse_bool(r.get("perspectiva_negocio")),
                "titulo_review":        r.get("titulo_review"),
                "pros":                 r.get("pros"),
                "contras":              r.get("contras"),
                "conselho_presidencia": r.get("conselho_presidencia"),
                "source_file":          source_file,
                "processed_at":         r.get("_processed_at"),
                "is_event_review":      is_event,
                "is_duplicate":         False,
                "quality_score":        quality,
            })

        if batch:
            session.execute(
                text("""
                    INSERT INTO reviews (
                        company_id, cargo, localizacao, data_review,
                        status_funcionario, tempo_empresa, avaliacao_geral,
                        recomendaria, aprovacao_ceo, perspectiva_negocio,
                        titulo_review, pros, contras, conselho_presidencia,
                        source_file, processed_at, is_event_review,
                        is_duplicate, quality_score
                    ) VALUES (
                        :company_id, :cargo, :localizacao, :data_review,
                        :status_funcionario, :tempo_empresa, :avaliacao_geral,
                        :recomendaria, :aprovacao_ceo, :perspectiva_negocio,
                        :titulo_review, :pros, :contras, :conselho_presidencia,
                        :source_file, :processed_at, :is_event_review,
                        :is_duplicate, :quality_score
                    )
                """),
                batch,
            )
            session.commit()
            stats["inserted"] += len(batch)
            print(f"    ✅ {len(batch)} reviews inseridas")

    return stats


# ── Jobs (vagas_market_intelligence.csv) ─────────────────────────────────────

def ingest_jobs(session, company_map: dict) -> dict:
    stats = {"inserted": 0, "skipped_no_company": 0, "skipped_duplicate": 0}

    if not JOBS_MARKET.exists():
        print(f"  ⚠️  {JOBS_MARKET.name} não encontrado — pulando jobs")
        return stats

    df = pd.read_csv(JOBS_MARKET, dtype={"id": str})
    print(f"\n  📂 {JOBS_MARKET.name} — {len(df)} vagas brutas")

    # IDs já inseridos
    existing_ids = set(
        str(row[0]) for row in session.execute(
            text("SELECT id FROM jobs")
        ).fetchall()
    )

    batch_jobs   = []
    batch_skills = []

    # Carrega skills por vaga se disponível
    skills_df = None
    if JOBS_SKILLS.exists():
        skills_df = pd.read_csv(JOBS_SKILLS, dtype={"id": str})
        skills_df = skills_df.set_index("id")

    for _, row in tqdm(df.iterrows(), total=len(df), desc="    Preparando jobs", leave=False):
        job_id     = str(row["id"])
        empresa    = str(row.get("empresa", ""))
        slug       = slug_from_empresa(empresa)
        company_id = company_map.get(slug) if slug else None

        if not company_id:
            # Insere empresa desconhecida como nova company se ainda não existe
            # Por ora pula — só insere empresas já cadastradas
            stats["skipped_no_company"] += 1
            continue

        if job_id in existing_ids:
            stats["skipped_duplicate"] += 1
            continue

        work_model = normalize_work_model(row.get("modelo_trabalho"))

        batch_jobs.append({
            "id":             int(job_id),
            "company_id":     company_id,
            "titulo":         row.get("titulo"),
            "localizacao":    f"{row.get('cidade', '')}, {row.get('estado', '')}".strip(", "),
            "seniority_score": _seniority_to_score(str(row.get("senioridade", ""))),
            "area":           str(row.get("area", ""))[:50],
            "work_model":     work_model,
            "has_ml":         False,
            "has_cloud":      False,
            "has_backend":    False,
            "has_data":       False,
            "has_frontend":   False,
        })

        # Skills por vaga
        if skills_df is not None and job_id in skills_df.index:
            sr = skills_df.loc[job_id]
            for skill in SKILL_COLS:
                if skill in sr.index and str(sr[skill]).lower() == "true":
                    batch_skills.append({"job_id": int(job_id), "skill": skill})

    if batch_jobs:
        # Enriquece has_* flags a partir das skills
        job_skill_map: dict[int, set] = {}
        for s in batch_skills:
            job_skill_map.setdefault(s["job_id"], set()).add(s["skill"])

        ml_skills      = {"machine_learning","deep_learning","nlp","tensorflow","pytorch","scikit_learn"}
        cloud_skills   = {"aws","gcp","azure"}
        backend_skills = {"python","java","golang","kotlin","scala","c#","api_rest","microservices"}
        data_skills    = {"sql","spark","kafka","airflow","dbt","databricks","bigquery","pandas"}
        front_skills   = {"javascript","typescript","react","vue","angular"}

        for j in batch_jobs:
            jid    = j["id"]
            skills = job_skill_map.get(jid, set())
            j["has_ml"]       = bool(skills & ml_skills)
            j["has_cloud"]    = bool(skills & cloud_skills)
            j["has_backend"]  = bool(skills & backend_skills)
            j["has_data"]     = bool(skills & data_skills)
            j["has_frontend"] = bool(skills & front_skills)

        session.execute(
            text("""
                INSERT INTO jobs (
                    id, company_id, titulo, localizacao,
                    seniority_score, area, work_model,
                    has_ml, has_cloud, has_backend, has_data, has_frontend
                ) VALUES (
                    :id, :company_id, :titulo, :localizacao,
                    :seniority_score, :area, :work_model,
                    :has_ml, :has_cloud, :has_backend, :has_data, :has_frontend
                )
            """),
            batch_jobs,
        )
        session.commit()
        stats["inserted"] += len(batch_jobs)
        print(f"    ✅ {len(batch_jobs)} vagas inseridas")

    if batch_skills:
        session.execute(
            text("INSERT INTO job_skills (job_id, skill) VALUES (:job_id, :skill)"),
            batch_skills,
        )
        session.commit()
        print(f"    ✅ {len(batch_skills)} skills inseridas")

    return stats


def _seniority_to_score(s: str) -> int:
    s = s.lower()
    if "junior" in s or "jr" in s or "estagi" in s:
        return 1
    if "pleno" in s or "mid" in s:
        return 2
    if "senior" in s or "sênior" in s or "sr" in s:
        return 3
    if "especialista" in s or "lead" in s or "staff" in s or "principal" in s:
        return 4
    if "gerente" in s or "manager" in s or "diretor" in s or "head" in s:
        return 5
    return 0  # nao_classificado


# ── Resumo por empresa (company_dimension_stats pre-seed) ────────────────────

def ingest_resumo(session, company_map: dict):
    """
    Lê vagas_resumo.csv e armazena os dados de mercado como
    metadados na tabela companies (via UPDATE) para uso no dashboard.
    Por ora apenas exibe um resumo — será usado no pipeline 04_aggregate.
    """
    if not JOBS_RESUMO.exists():
        return

    df = pd.read_csv(JOBS_RESUMO)
    print(f"\n  📊 Resumo de vagas por empresa:")
    for _, row in df.iterrows():
        slug = slug_from_empresa(str(row.get("empresa", "")))
        if slug and slug in company_map:
            pct_on = row.get("pct_presencial", 0)
            pct_hy = row.get("pct_hibrido", 0)
            pct_re = row.get("pct_remoto", 0)
            total  = row.get("total_vagas", 0)
            area   = row.get("area", "")
            print(
                f"    {slug:15s} | {area:15s} | "
                f"{int(total):3d} vagas | "
                f"presencial {pct_on:.0%} | "
                f"híbrido {pct_hy:.0%} | "
                f"remoto {pct_re:.0%}"
            )


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Pipeline 01 — Ingestão de dados brutos")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:
        company_map = get_company_map(session)
        print(f"\n✅ Companies no banco: {list(company_map.keys())}")

        # ── Reviews ──
        print("\n📝 Ingerindo reviews...")
        r_stats = ingest_reviews(session, company_map)
        print(f"\n  Resumo reviews:")
        print(f"    ✅ Inseridas:          {r_stats['inserted']}")
        print(f"    ⏭️  Duplicadas:         {r_stats['skipped_duplicate']}")
        print(f"    ⚠️  Incompletas:        {r_stats['skipped_incomplete']}")
        print(f"    🎪 Reviews de evento:  {r_stats['skipped_event']} (inseridas com flag)")
        print(f"    ❌ Empresa não mapeada:{r_stats['skipped_no_company']}")

        # ── Jobs ──
        print("\n💼 Ingerindo vagas...")
        j_stats = ingest_jobs(session, company_map)
        print(f"\n  Resumo vagas:")
        print(f"    ✅ Inseridas:          {j_stats['inserted']}")
        print(f"    ⏭️  Duplicadas:         {j_stats['skipped_duplicate']}")
        print(f"    ❌ Empresa não mapeada:{j_stats['skipped_no_company']}")

        # ── Resumo de mercado ──
        ingest_resumo(session, company_map)

        # ── Totais finais ──
        total_reviews = session.execute(text("SELECT COUNT(*) FROM reviews")).scalar()
        total_jobs    = session.execute(text("SELECT COUNT(*) FROM jobs")).scalar()
        total_skills  = session.execute(text("SELECT COUNT(*) FROM job_skills")).scalar()

        print(f"\n{'=' * 65}")
        print(f"  ✅ Banco atualizado:")
        print(f"     {total_reviews:,} reviews")
        print(f"     {total_jobs:,} vagas")
        print(f"     {total_skills:,} skills de vagas")
        print(f"{'=' * 65}")
        print(f"\n🚀 Próximo passo: python -m app.pipeline.02_normalize")


if __name__ == "__main__":
    main()