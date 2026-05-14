"""
ifdata_bacen.py v2
==================
A API OData do IF.data retorna 403 em ambientes externos (allowlist de IPs).
Funciona normalmente no browser/máquina local.

Esta versão usa a interface web do IF.data diretamente
via requests simulando o browser, que é como o site funciona.

COMO USAR MANUALMENTE (backup se o script falhar):
    1. Acesse https://www3.bcb.gov.br/ifdata/
    2. Selecione "Dados por Instituição"
    3. Busque "C6 Bank" → clique em "Exportar dados"
    4. Repita para cada concorrente
    5. Salve os CSVs em data/processed/ifdata_EMPRESA.csv
"""

import requests
import pandas as pd
import json
from pathlib import Path

OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Base da API interna que o site ifdata usa
# (descoberta via DevTools do browser → Network tab)
IFDATA_BASE = "https://www3.bcb.gov.br/ifdata/rest"

# Códigos de instituição no IF.data (diferente do CNPJ)
# Para encontrar: acesse ifdata, busque a instituição, o código aparece na URL
# Exemplo: /ifdata/#/2023-12-31/i/2/s/1 → "2" é o código do Itaú
INSTITUICOES_CODIGO = {
    "C6 Bank":        None,   # descobrir via busca por nome
    "Nubank":         None,
    "Itaú Unibanco":  None,
    "Bradesco":       None,
    "BTG Pactual":    None,
    "XP Investimentos": None,
    "Santander":      None,
    "Banco Inter":    None,
}

HEADERS = {
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":           "application/json, text/plain, */*",
    "Referer":          "https://www3.bcb.gov.br/ifdata/",
    "Origin":           "https://www3.bcb.gov.br",
}


def buscar_instituicao_por_nome(nome: str) -> list:
    """
    Busca o código interno da instituição no IF.data pelo nome.
    """
    url = f"{IFDATA_BASE}/pesquisaIfByNome"
    params = {"nome": nome}

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.ok:
            return resp.json()
        else:
            return []
    except Exception as e:
        return []


def buscar_dados_instituicao(codigo_if: str, periodo: str = "2024-12-31") -> dict:
    """
    Busca os dados de uma IF para um período específico.
    Período: ano-mes-dia do fim do trimestre (ex: 2024-12-31, 2024-09-30)
    """
    url = f"{IFDATA_BASE}/listaValorRelatorio"
    params = {
        "codIf":     codigo_if,
        "data":      periodo,
        "referencia": "I",  # I=Individual, C=Consolidado
    }

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.ok:
            return resp.json()
        return {}
    except Exception as e:
        return {}


def run():
    print("=" * 60)
    print("IF.data Banco Central v2")
    print("=" * 60)

    # Teste de conectividade
    print("\nTestando conectividade com IF.data...")
    try:
        r = requests.get(
            f"{IFDATA_BASE}/pesquisaIfByNome",
            params={"nome": "C6"},
            headers=HEADERS,
            timeout=15
        )
        print(f"Status: {r.status_code}")

        if r.status_code == 403:
            print("""
╔══════════════════════════════════════════════════════════╗
║  IF.data retorna 403 em ambientes de servidor            ║
║  A API funciona apenas em browsers ou IPs residenciais   ║
╠══════════════════════════════════════════════════════════╣
║  ALTERNATIVA: Coleta manual (5 minutos por empresa)      ║
║                                                          ║
║  1. Acesse https://www3.bcb.gov.br/ifdata/               ║
║  2. Clique em "Dados por Instituição"                    ║
║  3. No campo de busca, digite o nome da instituição      ║
║  4. Clique no nome da IF nos resultados                  ║
║  5. Selecione o período: 4T2024 ou mais recente          ║
║  6. Clique em "Exportar" → salve como CSV                ║
║  7. Repita para: C6 Bank, Nubank, Itaú, Bradesco,        ║
║     BTG Pactual, XP, Santander, Inter                    ║
║  8. Salve em: data/processed/ifdata_NOME_EMPRESA.csv     ║
╚══════════════════════════════════════════════════════════╝

Campos de interesse no IF.data:
  - Funcionários (número de empregados)
  - Total de Ativos
  - Patrimônio Líquido
  - Resultado do Período

Para C6 Bank especificamente, o IF.data é a ÚNICA fonte
pública oficial de headcount, pois o C6 não é listado em bolsa.
""")
            return

        # Se funcionou
        if r.ok:
            data = r.json()
            print(f"✓ Conectividade OK — {len(data)} instituições encontradas")
            print(json.dumps(data[:3], indent=2, ensure_ascii=False))

            # Buscar todas as instituições de interesse
            for nome, _ in INSTITUICOES_CODIGO.items():
                print(f"\nBuscando: {nome}")
                resultados = buscar_instituicao_por_nome(nome.split()[0])
                if resultados:
                    for r_item in resultados[:3]:
                        print(f"  {r_item}")

    except Exception as e:
        print(f"Erro de conexão: {e}")
        print("\nRode este script na sua máquina local — não em servidor.")


if __name__ == "__main__":
    run()