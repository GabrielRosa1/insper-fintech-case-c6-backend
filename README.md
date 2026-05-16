## ⚠️ Sobre os dados (CSV grandes)

Os arquivos `.csv`, que fizeram parte da análise, da pasta `data/raw/` **não estão incluídos no repositório**.

Isso foi feito porque esses arquivos são muito grandes e não são adequados para versionamento com Git.

---

## 📥 Como obter os dados

Para gerar ou baixar os dados necessários, utilize os scripts disponíveis na pasta `scripts/`.

### Passo a passo:

1. Acesse a pasta de scripts:

   ```bash
   cd scripts
   ```

2. Execute o(s) script(s) de coleta/download:

   ```bash
   python nome_do_script.py
   ```
---

## 💡 Observação

Sempre que alguém clonar este repositório, será necessário rodar os scripts da pasta `scripts/` para reconstruir os dados locais.

---

## 🚀 Requisitos

Instale as dependências antes de rodar os scripts:

```bash
pip install -r requirements.txt
```

---
## Estrutura do projeto (backend)

backend/
├── alembic/
│   ├── versions/
│   │   ├── 001_initial_schema.py        # Tabelas + pgvector
│   │   ├── 002_seed_companies_dims.py   # Seed C6, Nubank, dimensões
│   │   └── 003_indexes.py               # Índices de performance
│   ├── env.py
│   └── alembic.ini
│
├── app/
│   ├── models/                          # SQLAlchemy models
│   │   ├── company.py
│   │   ├── dimension.py
│   │   ├── review.py
│   │   ├── job.py
│   │   ├── event.py
│   │   ├── insight.py
│   │   └── gap.py
│   │
│   ├── pipeline/                        # Pipeline de análise
│   │   ├── 01_ingest.py                 # JSON/CSV → DB
│   │   ├── 02_normalize.py              # Normaliza cargos, áreas
│   │   ├── 03_analyze_micro.py          # Claude por review (paralelo)
│   │   ├── 04_aggregate.py              # Stats agregadas
│   │   ├── 05_detect_events.py          # Change-point detection
│   │   ├── 06_gap_analysis.py           # Reviews × Vagas
│   │   ├── 07_insights_macro.py         # Claude gera insights
│   │   └── 08_embeddings.py             # Embeddings para RAG
│   │
│   ├── ai/
│   │   ├── client.py                    # Wrapper Anthropic SDK
│   │   ├── prompts/                     # Prompts versionados
│   │   │   ├── micro_analysis.md
│   │   │   ├── macro_synthesis.md
│   │   │   └── rag_qa.md
│   │   └── schemas.py                   # Pydantic p/ outputs estruturados
│   │
│   ├── api/                             # FastAPI routes
│   │   ├── companies.py
│   │   ├── dimensions.py
│   │   ├── insights.py
│   │   ├── reviews.py
│   │   └── chat.py                      # RAG endpoint
│   │
│   ├── database.py
│   └── config.py
│
├── data/
│   ├── raw/                             # JSONs originais
│   └── processed/                       # Após pipeline
│
├── requirements.txt
└── .env