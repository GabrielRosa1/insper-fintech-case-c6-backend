"""
Pipeline Step 02 — Normalização e enriquecimento de reviews

O que faz:
  • Normaliza cargo (remove ruídos, padroniza títulos)
  • Infere nivel_senioridade a partir do cargo
  • Infere area_funcional a partir do cargo
  • Recalcula quality_score com critérios mais ricos
  • Marca reviews suspeitas de serem de eventos (campanha fotos etc.)
  • Detecta linguagem emocional (saudosismo, revolta, admiração)
  • Normaliza status_funcionario e tempo_empresa

Idempotente: só processa reviews sem nivel_senioridade preenchido
             (ou com analysis_version nula).

"""

import sys
import re
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import get_session

# ── Mapas de normalização ─────────────────────────────────────────────────────

# Senioridade: padrões regex → nível
SENIORITY_PATTERNS = [
    (r"\bestagi[aá]ri[oa]\b|\bintern\b|\bjovem aprendiz\b",                    "estagiario"),
    (r"\bjunior\b|\bjr\.?\b|\bjúnior\b|\bassistente\b|\bassociate\b",           "junior"),
    (r"\bpleno\b|\bmid\b|\bii\b|\b2\b",                                        "pleno"),
    (r"\bsenior\b|\bsênior\b|\bsr\.?\b|\b3\b",                                 "senior"),
    (r"\blead\b|\btechlead\b|\btech lead\b|\bstaff\b|\bprincipal\b|\blíder\b", "lead"),
    (r"\bgerente\b|\bmanager\b|\bhead\b|\bdiretor\b|\bdirector\b|\bvp\b"
     r"|\bvice.president\b|\bc-level\b|\bceo\b|\bcto\b|\bcfo\b|\bcoo\b",       "lideranca"),
    (r"\bespecialista\b|\bspecialist\b|\bexpert\b",                             "especialista"),
]

# Área funcional: padrões regex → área
AREA_PATTERNS = [
    (r"\bengenhei[ro]\b|\bsoftware\b|\bdesenvolvedor\b|\bdeveloper\b"
     r"|\bbackend\b|\bfrontend\b|\bfull.?stack\b|\bsre\b|\bdevops\b"
     r"|\binfrastructure\b|\binfra\b|\bplatform\b|\bmobile\b|\bclojure\b",     "engenharia"),
    (r"\bdados\b|\bdata\b|\banalytics\b|\banalytic\b|\bscientist\b"
     r"|\bmachine.learning\b|\bml\b|\bai\b|\bbusiness.intel\b|\bintelig",       "dados"),
    (r"\bproduto\b|\bproduct\b|\bpm\b|\bpmo\b|\bapm\b",                        "produto"),
    (r"\bdesign\b|\bux\b|\bui\b|\bdesigner\b",                                 "design"),
    (r"\batendimento\b|\bcustomer\b|\bcx\b|\bxpert\b|\bxpeer\b|\bxforce\b"
     r"|\bxmart\b|\bxsmart\b|\brelacionamento\b|\bsupport\b|\bcs\b",           "atendimento"),
    (r"\bmarketing\b|\bcontent\b|\bcomunica[cç]\b|\binfluencer\b",              "marketing"),
    (r"\bfinan[cç]\b|\bcontroladoria\b|\baccounti\b|\bfp&a\b|\baudit\b"
     r"|\bcontabilidade\b|\btesoura\b|\brisco\b|\bcredit\b",                    "financeiro"),
    (r"\bjurídico\b|\bjuridico\b|\badvogado\b|\bcompliance\b|\blegal\b"
     r"|\bregulat\b",                                                            "juridico"),
    (r"\brh\b|\brecursos.humanos\b|\bhrbp\b|\bpeople\b|\btalent\b"
     r"|\brecrutamento\b|\bcultura\b",                                           "rh_pessoas"),
    (r"\boperac\b|\bopera[cç]\b|\blogistic\b|\bsupply\b|\bprocess\b",          "operacoes"),
    (r"\bvendas\b|\bsales\b|\bcomercial\b|\baccount\b|\bbusiness.dev\b",        "vendas"),
    (r"\bseguran[cç]a\b|\bsecurity\b|\bfrau[de]\b|\bprevenc\b|\bprevên",       "seguranca_fraude"),
]

# Linguagem emocional
SAUDOSISMO_PATTERNS = [
    r"já foi bom", r"já foi melhor", r"era a empresa dos sonhos",
    r"já foi incrível", r"era incrível", r"foi ótimo", r"saudades",
    r"não é mais o que era", r"mudou muito", r"perdeu a essência",
    r"perdeu a cultura", r"era diferente", r"tempos melhores",
    r"voltaria no tempo", r"época boa", r"já foi",
]

REVOLTA_PATTERNS = [
    r"absurdo", r"inadmissível", r"vergonhoso", r"desrespeito",
    r"humilhação", r"humilhante", r"exploração", r"explorad",
    r"escravid", r"lamentável", r"patético", r"fuja", r"fujam",
    r"não vá", r"não entre", r"arrependimento", r"pior empresa",
    r"horrível", r"péssimo", r"terrível", r"revoltant",
]

ADMIRACAO_PATTERNS = [
    r"melhor empresa", r"melhor lugar", r"empresa dos sonhos",
    r"incrível", r"fantástico", r"sensacional", r"excepcional",
    r"top de mercado", r"referência", r"apaixonei", r"orgulho",
    r"recomendo", r"amei", r"adoro", r"amo trabalhar",
]

# Reviews suspeitas de eventos internos
EVENT_KEYWORDS = [
    "foto", "fotos profissionais", "linkedin", "sorvete",
    "campanha", "ação foto", "modelando", "book",
]


# ── Funções de inferência ────────────────────────────────────────────────────

def infer_seniority(cargo: str | None) -> str:
    if not cargo:
        return "nao_informado"
    c = cargo.lower()
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, c):
            return level
    return "nao_classificado"


def infer_area(cargo: str | None) -> str:
    if not cargo:
        return "nao_informado"
    c = cargo.lower()
    for pattern, area in AREA_PATTERNS:
        if re.search(pattern, c):
            return area
    return "outro"


def detect_linguagem(texto: str) -> dict:
    t = texto.lower()
    return {
        "saudosismo": any(re.search(p, t) for p in SAUDOSISMO_PATTERNS),
        "revolta":    any(re.search(p, t) for p in REVOLTA_PATTERNS),
        "admiracao":  any(re.search(p, t) for p in ADMIRACAO_PATTERNS),
    }


def is_event_review(titulo: str | None, pros: str | None) -> bool:
    texto = f"{titulo or ''} {pros or ''}".lower()
    return any(kw in texto for kw in EVENT_KEYWORDS)


def normalize_status(status: str | None) -> str | None:
    if not status:
        return None
    s = status.lower()
    if "atual" in s:
        return "atual"
    if "ex" in s or "former" in s:
        return "ex_funcionario"
    return status


def calc_quality_score(row: dict) -> float:
    """
    Score 0-1 baseado em:
    - Campos preenchidos (peso 0.4)
    - Tamanho do texto (peso 0.4)
    - Tem pros E contras (peso 0.2)
    """
    fields = [
        row.get("pros"), row.get("contras"), row.get("titulo_review"),
        row.get("conselho_presidencia"), row.get("cargo"),
        row.get("data_review"), row.get("avaliacao_geral"),
    ]
    fill_score = sum(1 for f in fields if f) / len(fields)

    text_len = len(str(row.get("pros") or "")) + len(str(row.get("contras") or ""))
    text_score = min(text_len / 300, 1.0)  # 300 chars = score máximo

    balance_score = 1.0 if (row.get("pros") and row.get("contras")) else 0.5

    return round(fill_score * 0.4 + text_score * 0.4 + balance_score * 0.2, 3)


def infer_momento(status: str | None, tempo: str | None) -> str:
    """Infere o momento da experiência do funcionário."""
    status_norm = normalize_status(status)
    if status_norm == "ex_funcionario":
        return "saida"

    if not tempo:
        return "nao_informado"
    t = tempo.lower()

    if any(x in t for x in ["menos de um", "< 1", "6 meses"]):
        return "inicio"
    if any(x in t for x in ["1 a 3", "mais de um", "mais de 1", "mais de 2"]):
        return "meio"
    if any(x in t for x in ["3 a 5", "mais de 3", "mais de 5", "mais de 8", "mais de 10"]):
        return "longo_prazo"
    return "meio"


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Pipeline 02 — Normalização e enriquecimento")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    with get_session() as session:
        # Busca reviews que ainda não foram normalizadas
        rows = session.execute(text("""
            SELECT id, cargo, localizacao, status_funcionario, tempo_empresa,
                   titulo_review, pros, contras, conselho_presidencia,
                   avaliacao_geral, data_review, is_event_review
            FROM reviews
            WHERE nivel_senioridade IS NULL
            ORDER BY id
        """)).fetchall()

        print(f"\n📋 Reviews para normalizar: {len(rows)}")

        if not rows:
            print("  ✅ Todas as reviews já estão normalizadas.")
            return

        updates = []
        stats = {
            "saudosismo": 0, "revolta": 0, "admiracao": 0,
            "event_flagged": 0,
        }
        area_dist  : dict[str, int] = {}
        level_dist : dict[str, int] = {}

        for row in tqdm(rows, desc="  Normalizando"):
            (id_, cargo, loc, status, tempo, titulo,
             pros, contras, conselho, nota, data_r, is_event) = row

            # Texto completo para análise de linguagem
            texto_completo = " ".join(filter(None, [
                str(titulo or ""), str(pros or ""),
                str(contras or ""), str(conselho or ""),
            ]))

            nivel   = infer_seniority(cargo)
            area    = infer_area(cargo)
            momento = infer_momento(status, tempo)
            ling    = detect_linguagem(texto_completo)
            evento  = is_event or is_event_review(titulo, pros)
            quality = calc_quality_score({
                "pros": pros, "contras": contras, "titulo_review": titulo,
                "conselho_presidencia": conselho, "cargo": cargo,
                "data_review": data_r, "avaliacao_geral": nota,
            })

            # Contagem para relatório
            if ling["saudosismo"]: stats["saudosismo"] += 1
            if ling["revolta"]:    stats["revolta"] += 1
            if ling["admiracao"]:  stats["admiracao"] += 1
            if evento:             stats["event_flagged"] += 1

            area_dist[area]   = area_dist.get(area, 0) + 1
            level_dist[nivel] = level_dist.get(nivel, 0) + 1

            updates.append({
                "id":                      id_,
                "nivel_senioridade":       nivel,
                "area_funcional":          area,
                "momento_experiencia":     momento,
                "status_funcionario":      normalize_status(status),
                "is_event_review":         evento,
                "quality_score":           quality,
                "tem_linguagem_saudosismo": ling["saudosismo"],
                "tem_linguagem_revolta":    ling["revolta"],
                "tem_linguagem_admiracao":  ling["admiracao"],
            })

        # Batch update
        session.execute(
            text("""
                UPDATE reviews SET
                    nivel_senioridade        = :nivel_senioridade,
                    area_funcional           = :area_funcional,
                    momento_experiencia      = :momento_experiencia,
                    status_funcionario       = :status_funcionario,
                    is_event_review          = :is_event_review,
                    quality_score            = :quality_score,
                    tem_linguagem_saudosismo = :tem_linguagem_saudosismo,
                    tem_linguagem_revolta    = :tem_linguagem_revolta,
                    tem_linguagem_admiracao  = :tem_linguagem_admiracao
                WHERE id = :id
            """),
            updates,
        )
        session.commit()

        # ── Relatório ──
        print(f"\n  ✅ {len(updates)} reviews normalizadas\n")

        print("  📊 Distribuição por área funcional:")
        for area, count in sorted(area_dist.items(), key=lambda x: -x[1]):
            bar = "█" * (count // 5)
            print(f"    {area:25s} {count:4d}  {bar}")

        print("\n  📊 Distribuição por senioridade:")
        order = ["estagiario","junior","pleno","senior","especialista","lead","lideranca","nao_classificado","nao_informado"]
        for nivel in order:
            count = level_dist.get(nivel, 0)
            if count:
                bar = "█" * (count // 5)
                print(f"    {nivel:20s} {count:4d}  {bar}")

        print("\n  🗣️  Linguagem emocional detectada:")
        print(f"    Saudosismo:  {stats['saudosismo']:4d} reviews")
        print(f"    Revolta:     {stats['revolta']:4d} reviews")
        print(f"    Admiração:   {stats['admiracao']:4d} reviews")
        print(f"    Eventos:     {stats['event_flagged']:4d} reviews (flagged)")

        print(f"\n{'=' * 65}")
        print(f"  🚀 Próximo passo: python -m app.pipeline.03_analyze_micro")
        print(f"{'=' * 65}")


if __name__ == "__main__":
    main()