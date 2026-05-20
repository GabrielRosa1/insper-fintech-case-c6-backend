#!/usr/bin/env python3
"""
Normaliza o campo 'empresa' para 'Mercado Livre'.
Uso: python scripts/normalize_mercadolivre.py mercadolivre.json
"""
import json, sys

INPUT = sys.argv[1] if len(sys.argv) > 1 else "mercadolivre.json"

with open(INPUT, encoding="utf-8") as f:
    reviews = json.load(f)

changed = 0
for r in reviews:
    if r.get("_no_complete_reviews"):
        continue
    old = r.get("empresa")
    if old != "Mercado Livre":
        r["empresa"] = "Mercado Livre"
        changed += 1
        print(f'  "{old}" → "Mercado Livre"')

with open(INPUT, "w", encoding="utf-8") as f:
    json.dump(reviews, f, ensure_ascii=False, indent=2)

real = [r for r in reviews if not r.get("_no_complete_reviews")]
print(f"\n✅ {changed} corrigidas — {len(real)} reviews no total, todas como 'Mercado Livre'")