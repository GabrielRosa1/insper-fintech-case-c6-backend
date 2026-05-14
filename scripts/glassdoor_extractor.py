#!/usr/bin/env python3
"""
Glassdoor Review Extractor v2
-----------------------------
Extrai reviews do Glassdoor a partir de prints de tela, lidando com:
- Múltiplas reviews por imagem
- Reviews parcialmente visíveis (descartadas automaticamente)
- Deduplicação inteligente baseada em conteúdo
- Processamento paralelo com barra de progresso e ETA
- Retry automático em caso de falha de API
- Resume: se interromper, basta rodar de novo

Uso:
  python glassdoor_extractor.py prints/*.png --empresa "C6 Bank"
  python glassdoor_extractor.py prints/ --empresa "C6 Bank" --output c6.json
  python glassdoor_extractor.py prints/ --workers 10

Requisitos:
  pip install anthropic tqdm
  set ANTHROPIC_API_KEY=sua_chave  (Windows)
  export ANTHROPIC_API_KEY=sua_chave  (Mac/Linux)
"""
from dotenv import load_dotenv
import anthropic
import base64
import json
import argparse
import sys
import os
import time
import hashlib
import glob
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

try:
    from tqdm import tqdm
except ImportError:
    print("Falta instalar tqdm. Rode: pip install tqdm")
    sys.exit(1)


MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 2500
MAX_RETRIES = 3
RETRY_DELAY = 2  # segundos

load_dotenv()

PROMPT = """Analise esta imagem do Glassdoor e extraia TODAS as reviews COMPLETAS visíveis.

REGRA CRÍTICA: Uma review é considerada COMPLETA apenas se tiver TODOS estes elementos visíveis:
- A nota com estrelas
- A seção "Prós" com texto legível
- A seção "Contras" com texto legível

Se uma review estiver cortada na parte de cima ou de baixo (faltando estrelas, prós ou contras), IGNORE-A completamente. É melhor extrair menos do que extrair dados incompletos.

Retorne SOMENTE este JSON (sem markdown, sem backticks, sem texto antes ou depois):

{
  "reviews": [
    {
      "empresa": "nome ou null",
      "titulo_review": "título da review ou null",
      "cargo": "cargo do autor ou null",
      "localizacao": "cidade, estado ou null",
      "data_review": "YYYY-MM-DD ou null",
      "status_funcionario": "Funcionário(a) atual | Ex-funcionário(a) | null",
      "tempo_empresa": "menos de um ano | mais de um ano | 1 a 3 anos | 3 a 5 anos | mais de 5 anos | null",
      "avaliacao_geral": 5.0,
      "recomendaria": true,
      "aprovacao_ceo": null,
      "perspectiva_negocio": false,
      "pros": "texto dos prós",
      "contras": "texto dos contras",
      "conselho_presidencia": "texto ou null se não houver seção"
    }
  ]
}

REGRAS DE INTERPRETAÇÃO:

1. Campos de aprovação (recomendaria, aprovacao_ceo, perspectiva_negocio):
   - check verde = true
   - X vermelho = false
   - traço cinza = null (neutro/não opinou)
   - Não visível na imagem = null

2. avaliacao_geral: número decimal de 1.0 a 5.0 conforme as estrelas

3. data_review: converta para ISO. Exemplos:
   - "9 de mar. de 2026" -> "2026-03-09"
   - "1 de abr. de 2026" -> "2026-04-01"
   - "15 de dez. de 2025" -> "2025-12-15"

4. pros, contras, conselho_presidencia: copie o texto EXATAMENTE como aparece, incluindo quebras de linha como espaços. Se a seção não existir, use null.

5. Se NAO houver nenhuma review completa na imagem, retorne: {"reviews": []}
"""


def encode_image(image_path: str):
    """Encode image to base64 and detect media type."""
    ext = Path(image_path).suffix.lower()
    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
    }
    media_type = media_types.get(ext, "image/png")
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode(), media_type


def extract_reviews_from_image(client, image_path):
    """Send image to Claude and extract list of reviews. Retries on failure."""
    image_data, media_type = encode_image(image_path)

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        }},
                        {"type": "text", "text": PROMPT}
                    ]
                }]
            )

            raw = response.content[0].text.strip()
            clean = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            return data.get("reviews", [])

        except json.JSONDecodeError as e:
            last_error = f"JSON inválido: {e}"
        except anthropic.APIError as e:
            last_error = f"API error: {e}"
            time.sleep(RETRY_DELAY * (attempt + 1))
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            time.sleep(RETRY_DELAY)

    raise RuntimeError(f"Falhou após {MAX_RETRIES} tentativas. Último erro: {last_error}")


def content_hash(review):
    """Hash baseado em conteúdo para detectar duplicatas entre prints diferentes."""
    parts = [
        str(review.get("data_review", "")),
        str(review.get("cargo", "")),
        str(review.get("avaliacao_geral", "")),
        (review.get("pros") or "")[:80].strip(),
    ]
    key = "|".join(parts).lower()
    return hashlib.md5(key.encode()).hexdigest()


def load_state(output_path, errors_path):
    """Carrega reviews existentes, hashes de conteúdo e arquivos já processados."""
    reviews = []
    hashes = set()
    processed_files = set()

    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            reviews = json.load(f)
            for r in reviews:
                if not r.get("_no_complete_reviews"):
                    hashes.add(content_hash(r))
                if r.get("_source_file"):
                    processed_files.add(r["_source_file"])

    errors = []
    if os.path.exists(errors_path):
        with open(errors_path, "r", encoding="utf-8") as f:
            errors = json.load(f)

    return reviews, hashes, processed_files, errors


def save_reviews(reviews, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=2)


def save_errors(errors, errors_path):
    with open(errors_path, "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)


def expand_paths(inputs):
    """Expande diretórios e padrões glob em paths de arquivos."""
    files = []
    valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    for item in inputs:
        if os.path.isdir(item):
            for ext in valid_exts:
                files.extend(glob.glob(os.path.join(item, f"*{ext}")))
                files.extend(glob.glob(os.path.join(item, f"*{ext.upper()}")))
        elif "*" in item or "?" in item:
            files.extend(glob.glob(item))
        elif os.path.exists(item):
            files.append(item)
    return sorted(set(files))


def print_summary(reviews, errors, elapsed):
    total = len(reviews)
    empresas = {}
    distribuicao = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    recomendam = {True: 0, False: 0, None: 0}
    notas = []

    for r in reviews:
        emp = r.get("empresa") or "Desconhecida"
        empresas[emp] = empresas.get(emp, 0) + 1

        nota = r.get("avaliacao_geral")
        if nota:
            notas.append(nota)
            bucket = int(round(nota))
            if bucket in distribuicao:
                distribuicao[bucket] += 1

        rec = r.get("recomendaria")
        if rec in recomendam:
            recomendam[rec] += 1

    print("\n" + "=" * 50)
    print("  RESUMO DO DATASET")
    print("=" * 50)
    print(f"  Total de reviews: {total}")
    print(f"  Erros: {len(errors)}")
    print(f"  Tempo total: {elapsed:.1f}s")

    if total > 0:
        print(f"\n  Por empresa:")
        for emp, count in sorted(empresas.items(), key=lambda x: -x[1]):
            print(f"    - {emp}: {count}")

        print(f"\n  Distribuição de notas:")
        max_val = max(distribuicao.values()) if distribuicao.values() else 1
        for stars in [5, 4, 3, 2, 1]:
            count = distribuicao.get(stars, 0)
            bar = "#" * int(count / max_val * 20) if max_val > 0 else ""
            print(f"    {stars} estrelas: {count:4d}  {bar}")

        if notas:
            print(f"\n  Nota média: {sum(notas)/len(notas):.2f}")

        print(f"\n  Recomendariam:")
        print(f"    Sim:    {recomendam[True]}")
        print(f"    Não:    {recomendam[False]}")
        print(f"    Neutro: {recomendam[None]}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Extrai reviews do Glassdoor de prints para JSON",
    )
    parser.add_argument("inputs", nargs="+", help="Imagens, pastas ou padrões glob")
    parser.add_argument("--empresa", "-e", help="Empresa (sobrescreve se não detectada)")
    parser.add_argument("--output", "-o", default="reviews.json", help="Arquivo JSON de saída")
    parser.add_argument("--errors", default="errors.json", help="Arquivo de erros")
    parser.add_argument("--workers", "-w", type=int, default=5, help="Processos paralelos (padrão: 5)")
    parser.add_argument("--api-key", help="API key (ou ANTHROPIC_API_KEY env)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Erro: defina ANTHROPIC_API_KEY ou use --api-key")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    all_files = expand_paths(args.inputs)
    if not all_files:
        print("Nenhuma imagem encontrada nos paths fornecidos")
        sys.exit(1)

    reviews, hashes, processed_files, errors = load_state(args.output, args.errors)

    pending = [f for f in all_files if Path(f).name not in processed_files]
    skipped_files = len(all_files) - len(pending)

    print(f"\n{args.output}: {len(reviews)} entradas já salvas")
    print(f"{len(all_files)} imagens encontradas")
    if skipped_files:
        print(f"{skipped_files} já processadas (pulando)")
    print(f"{len(pending)} para processar com {args.workers} workers paralelos\n")

    if not pending:
        print("Tudo já foi processado!")
        real_reviews = [r for r in reviews if not r.get("_no_complete_reviews")]
        print_summary(real_reviews, errors, 0)
        return

    lock = Lock()
    stats = {"new_reviews": 0, "duplicates": 0, "incomplete": 0}
    start_time = time.time()

    def process_one(image_path):
        try:
            extracted = extract_reviews_from_image(client, image_path)
            file_name = Path(image_path).name
            new_count = 0
            dup_count = 0

            with lock:
                for review in extracted:
                    if args.empresa and not review.get("empresa"):
                        review["empresa"] = args.empresa

                    h = content_hash(review)
                    if h in hashes:
                        dup_count += 1
                        continue

                    hashes.add(h)
                    review["_source_file"] = file_name
                    review["_processed_at"] = datetime.now().isoformat()
                    reviews.append(review)
                    new_count += 1

                if not extracted:
                    stats["incomplete"] += 1
                    reviews.append({
                        "_source_file": file_name,
                        "_processed_at": datetime.now().isoformat(),
                        "_no_complete_reviews": True,
                    })

                stats["new_reviews"] += new_count
                stats["duplicates"] += dup_count
                save_reviews(reviews, args.output)

            return {"file": file_name, "new": new_count, "dup": dup_count}

        except Exception as e:
            file_name = Path(image_path).name
            with lock:
                errors.append({
                    "file": file_name,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                })
                save_errors(errors, args.errors)
            return {"file": file_name, "error": str(e)}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_one, f): f for f in pending}

        with tqdm(total=len(pending), desc="Processando", unit="img") as pbar:
            for future in as_completed(futures):
                result = future.result()
                if "error" in result:
                    pbar.set_postfix_str(f"erro: {result['file'][:30]}", refresh=False)
                else:
                    pbar.set_postfix({
                        "novas": stats["new_reviews"],
                        "dup": stats["duplicates"],
                    })
                pbar.update(1)

    elapsed = time.time() - start_time

    real_reviews = [r for r in reviews if not r.get("_no_complete_reviews")]
    # Mantém os markers no arquivo (pra resume funcionar), mas faz summary só das reais
    save_reviews(reviews, args.output)

    print(f"\nConcluído em {elapsed:.1f}s")
    print(f"  {stats['new_reviews']} novas reviews | {stats['duplicates']} duplicatas | {stats['incomplete']} imagens sem review completa | {len(errors)} erros")

    print_summary(real_reviews, errors, elapsed)

    if errors:
        print(f"\nErros salvos em {args.errors}. Você pode deletar esse arquivo e rodar novamente para tentar de novo.")


if __name__ == "__main__":
    main()