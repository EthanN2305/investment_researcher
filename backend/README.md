# Backend — Phase 1

FastAPI service. Stateless per request.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill ANTHROPIC_API_KEY, NEWSAPI_KEY
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET  /health` — status + which keys are configured
- `POST /research/{ticker}` — returns a `ResearchReport`
- `GET  /docs` — interactive OpenAPI UI

Example:

```bash
curl -X POST http://localhost:8000/research/MSFT | python -m json.tool
```

## Response shape

```json
{
  "ticker": "MSFT",
  "claims": [
    {"claim": "...", "evidence": "...", "source": "https://...", "confidence": 0.9}
  ],
  "summary": "...",
  "flags": ["no_recent_news"],
  "generated_at": "2026-...Z",
  "disclaimer": "..."
}
```

## Swapping providers

Every data source and the LLM implement a Protocol in `app/tools/base.py`.
To swap one, write a class with the same method and pass it in
`app/main.py:build_pipeline()` (or inject in tests). Nothing else changes.

## Error handling

- Unknown/invalid ticker → `404` (market data is required).
- News failure → report still returns, with a `missing_news` flag.
- Missing API keys → `503` with a clear message; `/health` still works.

## Tests

```bash
python -m tests.test_smoke
```
