# 🧠 Employer Branding Intelligence — Backend

> Pipeline de inteligência artificial para análise competitiva de employer branding entre **C6 Bank** e **Nubank**, baseado em 979 reviews reais do Glassdoor e 220 vagas do LinkedIn.

<br>

## 📌 Visão geral

Este repositório contém o pipeline completo de IA e a API REST que alimenta o dashboard de Employer Branding Intelligence do C6 Bank. O sistema transforma avaliações brutas de funcionários em insights estratégicos acionáveis para o C-level, utilizando modelos da Anthropic (Claude Haiku + Sonnet) e embeddings semânticos com Voyage AI.

**Custo total do pipeline:** ~$10,09 USD para analisar 979 reviews com qualidade de consultoria.

<br>

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                        PIPELINE DE IA                        │
│                                                             │
│  JSON/CSV  →  01_ingest  →  02_normalize  →  03_analyze     │
│                                    ↓              ↓         │
│              08_embeddings  ←  04_aggregate  ←  Claude Haiku│
│                    ↓              ↓                         │
│              pgvector RAG    05_events + 06_gaps             │
│                    ↓              ↓                         │
│              FastAPI API  ←  07_insights (Claude Sonnet)     │
│                    ↓                                        │
│              Next.js Dashboard                              │
└─────────────────────────────────────────────────────────────┘
```

<br>

## 🔬 Pipeline de 8 etapas

| Etapa | Script | Função | Modelo |
|-------|--------|--------|--------|
| 01 | `01_ingest.py` | Carrega JSONs de reviews e CSVs de vagas no PostgreSQL | — |
| 02 | `02_normalize.py` | Infere senioridade, área funcional e linguagem emocional | — |
| 03 | `03_analyze_micro.py` | Analisa cada review nas 9 dimensões com evidence quotes | Claude Haiku |
| 04 | `04_aggregate.py` | Calcula scores por empresa × dimensão × 8 períodos | — |
| 05 | `05_detect_events.py` | Detecta divisores de águas temporais (RTO, layoff, IPO) | — |
| 06 | `06_gap_analysis.py` | Cruza vagas LinkedIn com reviews (discurso vs realidade) | — |
| 07 | `07_insights_macro.py` | Gera 13 insights estratégicos C-level com plano de ação | Claude Sonnet |
| 08 | `08_embeddings.py` | Cria vetores semânticos para busca RAG em tempo real | Voyage-3 |

<br>

## 📊 Resultados do pipeline

```
companies                   2   C6 Bank + Nubank
dimensions                  9   liderança, cultura, salário, modelo trabalho...
reviews (total)           993
reviews (analisadas)      979   99,6% de sucesso
reviews (com embedding)   965   prontas para RAG
review_dimensions       3.966   análise micro completa
jobs                      220   vagas LinkedIn
job_skills                570   skills mapeadas
company_events             25   4 manuais + 21 auto-detectados
company_dimension_stats   140   9 dims × 2 empresas × 8 períodos
discourse_reality_gaps     16   gaps discurso vs realidade
insights                   13   insights estratégicos C-level
```

<br>

## 🚀 Início rápido

### Pré-requisitos

- Python 3.12+
- PostgreSQL com extensão `pgvector`
- Conta Anthropic (Claude API)
- Conta Voyage AI (embeddings)

### Instalação

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/insper-fintech-case-c6-backend
cd insper-fintech-case-c6-backend/backend

# Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows

# Instale as dependências
pip install -r requirements.txt
```

### Configuração

```bash
cp .env.example .env
```

Edite o `.env` com suas credenciais:

```env
DATABASE_URL=postgresql://user:password@host:port/db?sslmode=require
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...
ANALYSIS_VERSION=v1
PIPELINE_WORKERS=5
APP_ENV=production
```

### Banco de dados

```bash
# Aplica as migrations (cria tabelas + seeds)
alembic upgrade head
```

<br>

## ⚙️ Executando o pipeline

Execute as etapas em ordem. Cada etapa é **idempotente** — pode ser reexecutada com segurança.

```bash
# Etapa 01 — Ingestão
python -m app.pipeline.01_ingest

# Etapa 02 — Normalização
python -m app.pipeline.02_normalize

# Etapa 03 — Análise micro (~30-40 min, ~$6,00 USD)
python -m app.pipeline.03_analyze_micro

# Etapa 04 — Agregações
python -m app.pipeline.04_aggregate

# Etapa 05 — Detecção de eventos
python -m app.pipeline.05_detect_events

# Etapa 06 — Gap analysis
python -m app.pipeline.06_gap_analysis

# Etapa 07 — Insights macro (~2 min, ~$0,08 USD)
python -m app.pipeline.07_insights_macro

# Etapa 08 — Embeddings (~10 min, ~$0,01 USD)
python -m app.pipeline.08_embeddings
```

#### Opções úteis

```bash
# Testar análise micro com 10 reviews antes de rodar tudo
python -m app.pipeline.03_analyze_micro --limit 10

# Processar só uma empresa
python -m app.pipeline.03_analyze_micro --empresa c6_bank

# Re-processar mesmo com dados existentes
python -m app.pipeline.08_embeddings --force
```

<br>

## 🌐 API REST

### Subindo o servidor

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Acesse a documentação interativa em: `http://localhost:8000/docs`

### Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/api/v1/overview` | Scorecard C6 vs Nubank, KPIs, temas emergentes |
| `GET` | `/api/v1/insights` | 13 insights estratégicos com filtros |
| `GET` | `/api/v1/gaps` | Gaps discurso vs realidade por dimensão |
| `GET` | `/api/v1/timeline` | Sentimento mensal + eventos históricos |
| `POST` | `/api/v1/chat` | Chat RAG com evidências das reviews |
| `GET` | `/api/v1/chat/suggestions` | Sugestões de perguntas |
| `GET` | `/api/v1/reviews` | Reviews com filtros e paginação |
| `GET` | `/api/v1/reviews/{id}` | Detalhes de uma review com dimensões |
| `GET` | `/api/v1/reviews/stats/by-dimension` | Distribuição de sentimento por dimensão |
| `GET` | `/health` | Health check |

#### Exemplos de uso

```bash
# Scorecard completo
curl http://localhost:8000/api/v1/overview

# Insights críticos
curl "http://localhost:8000/api/v1/insights?prioridade=critica"

# Reviews negativas de engenharia sênior em 2024
curl "http://localhost:8000/api/v1/reviews?empresa=c6_bank&sentimento=negativo&area=engenharia&nivel=senior&ano=2024"

# Chat RAG
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Quais são os maiores riscos de retenção no C6 Bank?"}'
```

<br>

## 🗄️ Estrutura do banco de dados

```
companies               Empresas analisadas (C6 Bank, Nubank)
dimensions              9 dimensões de employer branding
reviews                 979 reviews com análise IA + embeddings
review_dimensions       Análise por dimensão de cada review
jobs                    220 vagas do LinkedIn
job_skills              570 skills mapeadas nas vagas
company_events          Eventos históricos (RTO, layoff, IPO)
company_dimension_stats Scores agregados por período
discourse_reality_gaps  Gaps vagas vs reviews
insights                13 insights estratégicos gerados
```

<br>

## 📁 Estrutura do projeto

```
.
├── .claude/
│   └── settings.local.json
├── .env
├── .gitattributes
├── .gitignore
├── .venv/
├── README.md
├── bancobv.json
├── bradesco.json
├── c6bank.json
├── CLAUDE.md
├── errors.json
├── ifood.json
├── itau.json
├── mercadolivre.json
├── nubank.json
├── requirements.txt
├── api/
│   ├── adzuna_vagas.py
│   ├── cvm_fre.py
│   ├── github_vagas.py
│   └── ifdata_bacen.py
├── backend/
│   ├── .claude/
│   │   └── settings.local.json
│   ├── .dockerignore
│   ├── .env
│   ├── .env.example
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── .gitkeep
│   │       ├── 314e6a2b8a60_chat_threads_messages.py
│   │       ├── 932debbd270f_initial_schema.py
│   │       └── c3375f4b841d_seed_companies_dimensions.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── ai/
│   │   │   ├── client.py
│   │   │   ├── schemas.py
│   │   │   └── prompts/
│   │   │       ├── macro_synthesis.md
│   │   │       ├── micro_analysis.md
│   │   │       └── rag_qa.md
│   │   ├── api/
│   │   │   ├── chat.py
│   │   │   ├── companies.py
│   │   │   ├── dimensions.py
│   │   │   ├── gaps.py
│   │   │   ├── insights.py
│   │   │   ├── overview.py
│   │   │   ├── reviews.py
│   │   │   └── timeline.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── chat.py
│   │   │   ├── company.py
│   │   │   ├── dimension.py
│   │   │   ├── event.py
│   │   │   ├── gap.py
│   │   │   ├── insight.py
│   │   │   ├── job.py
│   │   │   ├── review.py
│   │   │   ├── review_dimension.py
│   │   │   └── stats.py
│   │   └── pipeline/
│   │       ├── 01_ingest.py
│   │       ├── 02_normalize.py
│   │       ├── 03_analyze_micro.py
│   │       ├── 04_aggregate.py
│   │       ├── 05_detect_events.py
│   │       ├── 06_gap_analysis.py
│   │       ├── 07_insights_macro.py
│   │       └── 08_embeddings.py
│   └── data/
│       └── raw/
│           ├── c6bank.json
│           ├── nubank.json
│           ├── vagas_market_intelligence.csv
│           ├── vagas_resumo.csv
│           ├── vagas_skills.csv
│           └── vagas_skills_por_empresa.csv
├── data/
│   ├── apify/
│   │   ├── dataset_linkedin-jobs-scraper_2026-04-29_15-41-11-564.json
│   │   ├── glassdoor_cookie.json
│   │   ├── scraping_linkedin_1.json
│   │   ├── scraping_linkedin_2.json
│   │   ├── scraping_linkedin_3.json
│   │   ├── vagas_20260502_1410.json
│   │   ├── vagas_c6.json
│   │   ├── vagas_concorrentes.json
│   │   ├── vagas_todas_areas.json
│   │   └── scraping/
│   │       ├── data/
│   │       │   └── apify/
│   │       │       └── vagas_todas_areas.json
│   │       ├── glassdoor.py
│   │       ├── vagas_linkedin.py
│   │       ├── vagas_linkedin2.py
│   │       └── vagas_linkedin3.py
│   ├── glassdor_reviews/
│   │   └── reviews_c6.json
│   ├── processed/
│   │   ├── vagas_market_intelligence.csv
│   │   ├── vagas_resumo.csv
│   │   ├── vagas_skills.csv
│   │   └── vagas_skills_por_empresa.csv
│   └── raw/
│       ├── all_reviews.csv
│       ├── ds_salaries.csv
│       ├── glassdoor_reviews.csv
│       └── state_of_data_2024.csv
├── etl/
│   ├── c6_jobs_clean.csv
│   ├── c6_jobs_features.csv
│   ├── c6_jobs_skills.csv
│   ├── etl_vagas_c6.py
│   ├── etl_vagas_concorrentes.py
│   ├── etl_vagas_v2.py
│   ├── jobs_clean.csv
│   ├── jobs_features.csv
│   └── jobs_skills.csv
├── notebooks/
│   ├── all_reviews.ipynb
│   ├── glassdoor_reviews.ipynb
│   ├── market_intelligence_analysis.ipynb
│   ├── salaries.ipynb
│   ├── state_of_data_brazil_2024_2025.ipynb
│   ├── vagas_c6_x_concorrentes.ipynb
│   └── vagas_concorrentes.ipynb
└── scripts/
│   ├── glassdoor_extractor.py
│   ├── glassdoor_jobs_review_2_database.py
│   ├── glassdoor_review_database.py
│   ├── normalize_names.py
│   ├── normalize_nubank.py
│   ├── salary_database.py
│   ├── state_of_data_brazil_2024r.py
│   └── prints/
│       ├── bancobv/
│       ├── bradesco/
│       ├── c6/
│       ├── c6-recente/
│       ├── ifood/
│       ├── itau/
│       ├── mercadolivre/
│       ├── nubank/
│       └── nubank-recente/
```

<br>

## 🤖 Modelos de IA utilizados

| Modelo | Etapa | Uso | Custo aprox. |
|--------|-------|-----|--------------|
| `claude-haiku-4-5` | 03 | Análise micro de 979 reviews | ~$6,00 |
| `claude-sonnet-4-5` | 07 | Geração de insights estratégicos | ~$0,08 |
| `voyage-3` | 08 | Embeddings vetoriais (1024 dims) | ~$0,01 |

**Custo total do pipeline:** ~$10,09 USD

<br>

## 📈 Principais insights gerados

O pipeline identificou automaticamente:

- **Crise de liderança sistêmica** — Score 1.2/10 no C6 Bank, 88% de menções negativas em 277 reviews
- **Janela de captação RTO Nubank** — Êxodo de talentos sêniores após retorno presencial obrigatório (nov/2025)
- **Vantagem real em diversidade** — C6 Bank 5.5 vs Nubank 1.9 — gap de 3.6 pontos ignorado no recrutamento
- **Burnout endêmico** — Saúde mental 0.7/10 no C6 Bank, 91% negativo em 213 menções
- **Gap presencial crítico** — 97% das vagas exigem on-site, mas modelo de trabalho tem score 2.5/10

<br>

## 🔍 Como funciona o RAG

O sistema de chat usa **Retrieval-Augmented Generation** com busca semântica:

```
Pergunta do usuário
        ↓
Voyage-3 gera embedding da query (input_type="query")
        ↓
pgvector busca as 8 reviews mais similares por cosseno
        ↓
Reviews + resumos enviados como contexto ao Claude Haiku
        ↓
Resposta em português com citações rastreáveis
```

Exemplo de query semântica:
```
"burnout causado por liderança despreparada"
  → [0.511] Nubank | Cientista de dados sênior | ⭐2.0
  → [0.484] Nubank | Product designer | ⭐1.0
  → [0.483] Nubank | Analista de marketing | ⭐1.0
```

<br>

## 🛠️ Stack tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Linguagem | Python 3.12 |
| API | FastAPI 0.115 + Uvicorn |
| ORM | SQLAlchemy 2.0 + Alembic |
| Banco | PostgreSQL + pgvector (Aiven) |
| IA | Anthropic SDK (Claude Haiku + Sonnet) |
| Embeddings | Voyage AI (voyage-3, 1024 dims) |
| Validação | Pydantic v2 |
| Paralelismo | ThreadPoolExecutor (5 workers) |

<br>

## 📄 Licença

Projeto desenvolvido para a banca do Insper — uso interno C6 Bank. Dados de reviews são de domínio público (Glassdoor).

---

<p align="center">
  Desenvolvido com IA · Insper 2026
</p>