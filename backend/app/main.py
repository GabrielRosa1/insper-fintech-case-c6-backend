from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import overview, insights, gaps, timeline, chat, reviews
from dotenv import load_dotenv
import os


load_dotenv()

allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")

app = FastAPI(title="Employer Branding Intelligence API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overview.router, prefix="/api/v1")
app.include_router(insights.router, prefix="/api/v1")
app.include_router(gaps.router, prefix="/api/v1")
app.include_router(timeline.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(reviews.router, prefix="/api/v1")

@app.get("/health")
def health(): return {"status": "ok"}