# Smart Financial Advisor

AI-powered personal-finance assistant. Upload a bank-statement CSV, set a monthly budget, then ask the agent natural-language questions like *"Can I spend $500 on a new phone this month?"* — it grounds every numeric claim in tool-backed data, not hallucinated numbers.

## Quickstart

```bash
cp .env.example .env                # paste your OPENAI_API_KEY
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make up                             # postgres on :5432
make migrate                        # apply migrations
make test                           # full test suite
make run                            # uvicorn on :8000
```

Then visit `http://localhost:8000/` for the chat UI or `/docs` for Swagger.

## Architecture

Three layers: routers (validation only) → agents (tool-calling loop) → tools (deterministic capabilities). The LLM is one seam, every test mocks it. Postgres is the source of truth for budget, transactions, chat history, and trace events.

See `docs/superpowers/specs/2026-06-15-financial-advisor-design.md` for the full spec and `docs/superpowers/plans/2026-06-15-financial-advisor.md` for the implementation plan.
