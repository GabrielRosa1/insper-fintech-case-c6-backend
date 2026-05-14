"""
=============
Correções:
- CNPJs corrigidos para todas as empresas
- Busca por nome como fallback quando CNPJ não bate
- Suporte aos dois formatos de arquivo do CVM (pre e pós nov/2024)

EMPRESAS COBERTAS:
    ✓ Nubank (Nu Pagamentos S.A.)
    ✓ Itaú Unibanco Holding S.A.
    ✓ Bradesco
    ✓ BTG Pactual
    ✓ XP Investimentos (XP Inc. / XP Corretora)
    ✓ Banco Inter
    ✓ Santander Brasil
    ✗ C6 Bank (empresa privada — não listada na CVM)
"""

import requests
import pandas as pd
import zipfile
import io
from pathlib import Path

OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CVM_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS"
ANO = 2024

# CNPJs completos (14 dígitos, sem formatação)
# Fonte: Receita Federal + CVM
EMPRESAS = {
    # CNPJ 14 dígitos : Nome para exibição
    "60746948000112": "Bradesco",
    "60701190000104": "Itaú Unibanco",
    "90400888000142": "Santander Brasil",
    "30306294000126": "BTG Pactual",
    "00416968000101": "Banco Inter",
    # Nubank — a holding listada na CVM é a Nu Pagamentos ou NU Holdings
    # A entidade listada no Brasil é via CNPJ abaixo:
    "18236120000158": "Nubank (Nu Pagamentos)",
    # XP — listada como XP Inc. ou subsidiária brasileira
    "02332886000104": "XP Corretora",
    "33775974000104": "XP Inc (holding)",
}

# Termos para busca por nome (fallback quando CNPJ não bate)
NOMES_BUSCA = [
    "nubank", "nu pagamentos", "itaú", "itau", "bradesco",
    "btg pactual", "xp investimentos", "xp inc", "inter",
    "santander", "c6 bank"
]


def baixar_zip(ano: int):
    url = f"{CVM_BASE}/fre_cia_aberta_{ano}.zip"
    print(f"Baixando {url}...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    print(f"   ✓ {len(resp.content)/1024/1024:.1f} MB baixados")
    return resp.content


def ler_csv(zip_bytes, nome_arquivo):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        if nome_arquivo not in z.namelist():
            return pd.DataFrame()
        with z.open(nome_arquivo) as f:
            return pd.read_csv(f, sep=";", encoding="latin1", low_memory=False)


def filtrar_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    # Encontrar coluna de CNPJ
    col_cnpj = next((c for c in df.columns if "cnpj" in c.lower()), None)
    # Encontrar coluna de nome da empresa
    col_nome = next((c for c in df.columns
                     if "denom" in c.lower() or "nome" in c.lower() or "razao" in c.lower()), None)

    resultados = []

    # Filtro por CNPJ
    if col_cnpj:
        df[col_cnpj] = df[col_cnpj].astype(str).str.replace(r'\D', '', regex=True).str.zfill(14)
        mask_cnpj = df[col_cnpj].isin(EMPRESAS.keys())
        df_cnpj = df[mask_cnpj].copy()
        if not df_cnpj.empty:
            df_cnpj["_empresa"] = df_cnpj[col_cnpj].map(EMPRESAS)
            resultados.append(df_cnpj)

    # Filtro por nome (fallback)
    if col_nome and len(resultados) == 0:
        mask_nome = df[col_nome].str.lower().str.contains(
            "|".join(NOMES_BUSCA), na=False
        )
        df_nome = df[mask_nome].copy()
        if not df_nome.empty:
            df_nome["_empresa"] = df_nome[col_nome]
            resultados.append(df_nome)

    if resultados:
        return pd.concat(resultados).drop_duplicates()
    return pd.DataFrame()


def run():
    print("=" * 60)
    print("CVM FRE v2 — Headcount e Diversidade")
    print("=" * 60)

    zip_bytes = baixar_zip(ANO)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        arquivos = z.namelist()

    print(f"\n{len(arquivos)} arquivos no ZIP")

    # Identificar arquivos de empregados
    arqs_emp = [a for a in arquivos if "empregad" in a.lower()]
    print(f"{len(arqs_emp)} arquivos de empregados:\n")

    for arq in sorted(arqs_emp):
        print(f"  Processando: {arq}")
        df = ler_csv(zip_bytes, arq)

        if df.empty:
            print("    ⚠  Vazio")
            continue

        # Mostrar estrutura na primeira iteração
        if arq == sorted(arqs_emp)[0]:
            print(f"    Colunas: {list(df.columns)}")
            col_cnpj = next((c for c in df.columns if "cnpj" in c.lower()), None)
            if col_cnpj:
                sample = df[col_cnpj].astype(str).head(3).tolist()
                print(f"    CNPJs amostra: {sample}")

        df_filtrado = filtrar_df(df)

        if not df_filtrado.empty:
            nome_saida = arq.replace("fre_cia_aberta_empregado_", "").replace(f"_{ANO}.csv", "")
            output = OUTPUT_DIR / f"cvm_{nome_saida}.csv"
            df_filtrado.to_csv(output, index=False, encoding="utf-8-sig")
            empresas = df_filtrado["_empresa"].unique().tolist()
            print(f"    ✓ {len(df_filtrado)} registros | Empresas: {empresas}")
            print(f"    → {output}")
        else:
            print(f"    ⚠  Nenhuma empresa do peer group encontrada")
            # Debug: mostrar os CNPJs que existem no arquivo
            col_cnpj = next((c for c in df.columns if "cnpj" in c.lower()), None)
            if col_cnpj:
                cnpjs = df[col_cnpj].astype(str).str.replace(r'\D', '', regex=True).unique()[:5]
                print(f"    CNPJs no arquivo (amostra): {cnpjs.tolist()}")

    print(f"\n✓ Arquivos salvos em: {OUTPUT_DIR}")


if __name__ == "__main__":
    run()