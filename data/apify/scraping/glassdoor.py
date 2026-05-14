"""
scraping_glassdoor_v2.py
Versão robusta para MVP (resistente a bloqueios)
"""

import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from apify_client import ApifyClient

# =========================
# CONFIG
# =========================
load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
ACTOR_ID = "crawlerbros/glassdoor-reviews-scraper"

SCRIPT_DIR  = Path(__file__).parent
COOKIE_PATH = SCRIPT_DIR.parent / "glassdoor_cookie.json"
OUTPUT_PATH = SCRIPT_DIR.parent / "glassdoor_reviews_br.json"

MAX_REVIEWS = 40  # 🔥 importante: baixo para evitar bloqueio
MAX_RETRIES = 2

COMPANIES = [
    {"name": "C6 Bank", "slug": "c6", "url": "https://www.glassdoor.com/Reviews/C6-Bank-Reviews-E2469864.htm"},
    {"name": "Nubank", "slug": "nubank", "url": "https://www.glassdoor.com/Reviews/Nubank-Reviews-E827975.htm"},
    {"name": "Itaú", "slug": "itau", "url": "https://www.glassdoor.com/Reviews/Itau-Unibanco-Reviews-E10999.htm"},
    {"name": "XP", "slug": "xp", "url": "https://www.glassdoor.com/Reviews/XP-Investimentos-Reviews-E3707681.htm"},
]

# =========================
# COOKIE
# =========================
def load_cookie():
    if not COOKIE_PATH.exists():
        print("⚠ Sem cookie — chance de bloqueio alta")
        return None

    with open(COOKIE_PATH, "r", encoding="utf-8") as f:
        return f.read()


# =========================
# SCRAPING
# =========================
def scrape_company(client, company, cookie):
    print(f"\n🔎 {company['name']}")

    run_input = {
        "companyUrl": company["url"],
        "maxItems": MAX_REVIEWS,

        # 🔥 PROXY melhora MUITO
        "proxy": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"]
        },

        # 🔥 deixa mais humano
        "language": "en",
        "reviewRatings": ["ALL"],
    }

    if cookie:
        run_input["cookie"] = cookie

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"   tentativa {attempt}...")

            run = client.actor(ACTOR_ID).call(run_input=run_input)

            items = list(
                client.dataset(run["defaultDatasetId"]).iterate_items()
            )

            reviews = [
                r for r in items
                if r.get("pros") or r.get("cons") or r.get("rating")
            ]

            if len(reviews) == 0:
                raise Exception("0 reviews → provável bloqueio")

            print(f"   ✅ {len(reviews)} reviews")

            for r in reviews:
                r["_company"] = company["name"]

            return reviews

        except Exception as e:
            print(f"   ❌ erro: {e}")

            if attempt < MAX_RETRIES:
                wait = 10 * attempt
                print(f"   ⏳ esperando {wait}s...")
                time.sleep(wait)

    print("   ⚠ falhou geral")
    return []


# =========================
# MAIN
# =========================
def run():
    if not APIFY_TOKEN:
        raise ValueError("APIFY_TOKEN não encontrado")

    client = ApifyClient(APIFY_TOKEN)
    cookie = load_cookie()

    all_reviews = []

    for company in COMPANIES:
        reviews = scrape_company(client, company, cookie)
        all_reviews.extend(reviews)

        time.sleep(5)

    # salvar
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_reviews, f, ensure_ascii=False, indent=2)

    print("\n============================")
    print(f"TOTAL: {len(all_reviews)} reviews")
    print("============================")


if __name__ == "__main__":
    run()