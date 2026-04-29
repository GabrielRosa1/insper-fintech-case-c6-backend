import pandas as pd
import json
import re

# =========================
# CONFIG
# =========================
INPUT_FILE = "../data/apify/vagas_concorrentes.json"

# =========================
# SKILL DICTIONARY
# =========================
SKILLS_DICT = {
    "python": ["python"],
    "aws": ["aws", "amazon web services"],
    "kafka": ["kafka"],
    "sql": ["sql"],
    "ml": ["machine learning", "ml", "deep learning"],
    "java": ["java"],
    "kotlin": ["kotlin"],
    "docker": ["docker"],
    "kubernetes": ["kubernetes", "k8s"],
    "spark": ["spark"],
    "pandas": ["pandas"],
    "tensorflow": ["tensorflow"],
    "pytorch": ["pytorch"],
    "scala": ["scala"],
    "golang": ["go ", "golang"],
}

# =========================
# LOAD DATA
# =========================
def load_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return pd.DataFrame(data)

# =========================
# CLEAN TEXT
# =========================
def clean_text(text):
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return text

# =========================
# EXTRACT SKILLS
# =========================
def extract_skills(text):
    found = []
    for skill, keywords in SKILLS_DICT.items():
        for k in keywords:
            if k in text:
                found.append(skill)
                break
    return list(set(found))

# =========================
# SENIORITY SCORE
# =========================
def seniority_score(title):
    if not isinstance(title, str):
        return 0

    title = title.lower()

    if any(x in title for x in ["lead", "staff", "principal"]):
        return 4
    elif "senior" in title or "sr" in title:
        return 3
    elif any(x in title for x in ["pleno", "mid"]):
        return 2
    else:
        return 1

# =========================
# AREA CLASSIFICATION
# =========================
def classify_area(text):
    if any(x in text for x in ["machine learning", "data", "analytics", "sql"]):
        return "data"
    elif any(x in text for x in ["backend", "api", "microservices"]):
        return "backend"
    elif any(x in text for x in ["frontend", "react", "angular"]):
        return "frontend"
    else:
        return "other"

# =========================
# MAIN ETL
# =========================
def run_etl():
    print("Loading data...")
    df = load_data(INPUT_FILE)

    print("Cleaning...")
    df = df[[
        "id",
        "companyName",
        "title",
        "descriptionText",
        "seniorityLevel",
        "location"
    ]]

    df["text"] = (
        df["title"].fillna("") + " " + df["descriptionText"].fillna("")
    )

    df["text"] = df["text"].apply(clean_text)

    print("Extracting skills...")
    df["skills"] = df["text"].apply(extract_skills)

    print("Creating features...")
    df["seniority_score"] = df["title"].apply(seniority_score)
    df["area"] = df["text"].apply(classify_area)

    df["has_ml"] = df["skills"].apply(lambda x: "ml" in x)
    df["has_cloud"] = df["skills"].apply(lambda x: "aws" in x)
    df["has_backend"] = df["skills"].apply(
        lambda x: any(s in x for s in ["java", "kotlin"])
    )

    # =========================
    # TABLE 1: JOBS CLEAN
    # =========================
    jobs_df = df[[
        "id",
        "companyName",
        "title",
        "seniority_score",
        "area",
        "location"
    ]]

    # =========================
    # TABLE 2: SKILLS (EXPLODED)
    # =========================
    skills_df = df[["id", "skills"]].explode("skills")
    skills_df = skills_df.dropna()

    # =========================
    # TABLE 3: FEATURES
    # =========================
    features_df = df[[
        "id",
        "has_ml",
        "has_cloud",
        "has_backend",
        "seniority_score"
    ]]

    print("Saving outputs...")

    jobs_df.to_csv("jobs_clean.csv", index=False)
    skills_df.to_csv("jobs_skills.csv", index=False)
    features_df.to_csv("jobs_features.csv", index=False)

    print("Done.")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    run_etl()