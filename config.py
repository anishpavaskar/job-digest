"""Project configuration and profile data."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

MY_PROFILE = {
    "name": "Anish Pavaskar",
    "title": "Software Engineer II",
    "years_experience": 3,
    "skills_tier1": ["Python", "Go", "TypeScript", "Kubernetes", "Docker", "Terraform", "AWS"],
    "skills_tier2": ["Helm", "CI/CD", "PostgreSQL", "Redis", "gRPC", "FastAPI"],
    "target_roles": [
        "Backend Engineer",
        "Platform Engineer",
        "Infrastructure Engineer",
        "SRE",
        "DevOps",
    ],
    "target_levels": ["L4", "L5", "SWE II", "SWE III", "Staff", "Senior"],
    "preferred_domains": [
        "AI/ML infra",
        "developer tools",
        "fintech",
        "defense tech",
        "data infrastructure",
    ],
    "open_to_relocation": True,
    "preferred_locations": ["Remote", "San Francisco", "Bay Area", "New York", "Seattle"],
}

GREENHOUSE_COMPANIES = [
    {"slug": "anthropic", "name": "Anthropic"},
    {"slug": "anduril", "name": "Anduril Industries"},
    {"slug": "brex", "name": "Brex"},
    {"slug": "figma", "name": "Figma"},
    {"slug": "stripe", "name": "Stripe"},
    {"slug": "vercel", "name": "Vercel"},
    {"slug": "rippling", "name": "Rippling"},
    {"slug": "chime", "name": "Chime"},
    {"slug": "databricks", "name": "Databricks"},
    {"slug": "openai", "name": "OpenAI"},
    {"slug": "cohere", "name": "Cohere"},
    {"slug": "mistral", "name": "Mistral AI"},
    {"slug": "modal", "name": "Modal"},
    {"slug": "replit", "name": "Replit"},
    {"slug": "watershed", "name": "Watershed"},
    {"slug": "hex", "name": "Hex"},
    {"slug": "dbt-labs", "name": "dbt Labs"},
    {"slug": "cloudflare", "name": "Cloudflare"},
    {"slug": "datadog", "name": "Datadog"},
    {"slug": "crowdstrike", "name": "CrowdStrike"},
    {"slug": "warp", "name": "Warp"},
    {"slug": "together-ai", "name": "Together AI"},
    {"slug": "perplexity", "name": "Perplexity AI"},
    {"slug": "groq", "name": "Groq"},
    {"slug": "harvey", "name": "Harvey"},
]

SCORING_WEIGHTS = {
    "title_match": 0.30,
    "skills_match": 0.25,
    "level_match": 0.20,
    "domain_fit": 0.15,
    "location_fit": 0.10,
}

TOP_N_EMAIL = 8
MIN_SCORE = 55

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json").strip()
GMAIL_FROM = os.getenv("GMAIL_FROM", "").strip()
GMAIL_TO = os.getenv("GMAIL_TO", "").strip()
UNIFIED_API_KEY = os.getenv("UNIFIED_API_KEY", "").strip()
UNIFIED_LEVER_CONN_ID = os.getenv("UNIFIED_LEVER_CONN_ID", "").strip()
UNIFIED_ASHBY_CONN_ID = os.getenv("UNIFIED_ASHBY_CONN_ID", "").strip()
