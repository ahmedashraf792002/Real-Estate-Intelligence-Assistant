---
title: DarGlobal & Wasalt Assistant
emoji: 🏠
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# DarGlobal & Wasalt Assistant

A bilingual RAG chatbot for publicly available DarGlobal and Wasalt real-estate data.

The application combines:

- **DarGlobal public pages** scraped from `darglobal.co.uk`.
- **Wasalt public projects, listings, and pages** scraped from `wasalt.sa`.
- **Supabase PostgreSQL with pgvector** for documents and vector search.
- **BM25 keyword search + dense vector search** through Reciprocal Rank Fusion.
- **OpenRouter free models**, with multiple API keys and optional fallback providers.
- **FastAPI streaming chat API** and a responsive browser interface.
- **Docker** and **Hugging Face Spaces** deployment support.

The interface defaults to English and replies in Arabic when the latest user message is Arabic.

## Features

- RAG question answering with source URLs.
- Streaming model responses.
- Conversation history in browser local storage.
- Per-browser OpenRouter API key and free-model selection.
- Main and backup OpenRouter API keys.
- Optional OpenAI-compatible fallback provider.
- Supabase database index and local backup index.
- Local index fallback if Supabase is unavailable.
- Resumable JSONL scraping.
- Robots.txt enforcement and browser retry support.
- Health endpoint for index/backend diagnostics.
- Docker image with a prebuilt local backup index.

## Project structure

```text
src/
  app/
    main.py                 FastAPI routes, streaming, and rate limiting
    static/index.html       Chat interface and model settings
  rag/
    config.py               Environment configuration
    schema.py               Supabase table and pgvector setup
    database.py             Supabase/local document and index storage
    embeddings.py           Embedding model loading and vector creation
    indexing.py             Cleaning, chunking, embedding, and index creation
    retrieval.py            BM25, vector search, and Reciprocal Rank Fusion
    generation.py           OpenRouter providers, keys, models, and streaming
    pipeline.py             Question → search → prompt → answer flow
    evaluation.py           Retrieval and answer evaluation
    text.py                 Arabic/English tokenization
scripts/
  scrape.py                 Scraper entry-point wrapper
  scraper/                  Scraping modules and CLI
  rebuild_projects.py       Rebuild project documents when needed
data/
  raw/
    urls/                   Collected sitemap/project/listing URLs
    data/                   Scraped JSONL files
  eval_set.json             Optional real evaluation questions
index/                      Local backup index created by indexing
Dockerfile                  Container build configuration
pyproject.toml              Python dependencies and pytest configuration
.env.example                Example environment variables
```

## Requirements

- Python 3.11 or newer.
- [uv](https://docs.astral.sh/uv/) package manager.
- Supabase project with pgvector support.
- OpenRouter API key. The models use free tiers but availability and limits can change.
- Docker Desktop if running through Docker.
- Playwright Chromium if collecting data with browser fallback.
- Internet access for scraping and model requests.

## Quick start

Clone and enter the project:

```powershell
cd "d:\Ahmed Ashraf\Downloads\chatbot-v3_8\chatbot"
```

Install uv on Windows if it is not already installed:

```powershell
winget install --id astral-sh.uv -e
```

Install the project and scraper dependencies:

```powershell
uv sync --group scrape --group dev
uv run playwright install chromium
```

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

Add the real values in `.env`:

```dotenv
DATABASE_URL=postgresql://postgres.xxxxx:PASSWORD@SESSION-POOLER-HOST:5432/postgres

OPENROUTER_API_KEY=sk-or-v1-main-key
OPENROUTER_API_KEYS=sk-or-v1-backup-key-1,sk-or-v1-backup-key-2
```

Never commit `.env` or API keys to Git.

## Supabase setup

1. Create a Supabase project.
2. Open **Connect**.
3. Select **Session pooler**. This works with IPv4 and hosted environments.
4. Copy the PostgreSQL connection string into `DATABASE_URL`.
5. Initialize the tables:

```powershell
uv run python -m rag.schema
```

The tables can also be created automatically during `scrape.py push` or `rag.indexing`.

## Environment variables

### Database

| Variable | Required | Description |
|---|---:|---|
| `DATABASE_URL` | Recommended | Supabase/session-pooler PostgreSQL URL |
| `TEST_DATABASE_URL` | No | Separate database used by database tests |

### OpenRouter

| Variable | Required | Description |
|---|---:|---|
| `OPENROUTER_API_KEY` | Yes for generation | Main OpenRouter key |
| `OPENROUTER_API_KEYS` | No | Comma-separated backup keys |
| `OPENROUTER_MODELS` | No | Comma-separated preferred model IDs |
| `DISCOVER_FREE_MODELS` | No | Set `1` to discover free text models; default `1` |
| `KEY_COOLDOWN_SECONDS` | No | Exhausted-key cooldown; default `3600` |

### Optional fallback provider

Any OpenAI-compatible API can be used as a fallback:

```dotenv
FALLBACK_BASE_URL=https://api.example.com/openai/v1
FALLBACK_API_KEY=provider-key
FALLBACK_MODELS=model-name
```

### Search and application behavior

| Variable | Default | Description |
|---|---:|---|
| `USE_DENSE` | `1` | Enable dense vector search |
| `EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embedding model |
| `TOP_K` | `6` | Number of search chunks sent to the model |
| `CHUNK_CHARS` | `900` | Target chunk size |
| `MAX_HISTORY` | `8` | Maximum conversation messages kept |
| `MAX_MESSAGE_CHARS` | `1000` | Maximum characters per message |
| `RATE_LIMIT_PER_MIN` | `12` | Chat requests allowed per IP each minute |
| `PORT` | `7860` | Server port |

## Collect the data

Run each step separately:

```powershell
uv run python scripts/scrape.py urls
uv run python scripts/scrape.py darglobal
uv run python scripts/scrape.py projects --browser --delay 3
uv run python scripts/scrape.py pages --kinds static,category
uv run python scripts/scrape.py listings --n 2000 --lang both
uv run python scripts/scrape.py push
```

Or run the normal collection workflow in one command:

```powershell
uv run python scripts/scrape.py all --browser --delay 3 --n 2000 --lang both
```

### Scraper commands

| Command | Purpose |
|---|---|
| `urls` | Collect Wasalt sitemap URLs |
| `darglobal` | Scrape public DarGlobal pages |
| `projects` | Scrape Wasalt project data |
| `pages` | Scrape static/category/rental/product Wasalt pages |
| `listings` | Scrape individual Wasalt listings |
| `push` | Upload documents and projects to Supabase |
| `all` | Run the complete local collection workflow |

### Listing options

```powershell
uv run python scripts/scrape.py listings --n 2000 --lang en
uv run python scripts/scrape.py listings --n 2000 --lang ar
uv run python scripts/scrape.py listings --n 0 --lang both
```

- `--n 0` fetches all discovered listing URLs.
- `--lang en` uses English versions.
- `--lang ar` uses Arabic versions.
- `--lang both` uses both discovered language variants.
- `--limit N` limits a command to N pages.
- `--browser` enables Playwright browser retry.
- `--delay 3` sets a slower request pace.

Supported page kinds:

```text
static
category
rental_srp
rental_pdp
product
```

Example:

```powershell
uv run python scripts/scrape.py pages --kinds static,category,rental_srp,rental_pdp,product
```

### Scraper behavior

- URLs and scraped records are saved incrementally as JSONL files.
- Running a command again skips URLs already saved locally.
- Robots.txt rules are checked before every request.
- Failed pages are retried slowly with rotating user agents and sessions.
- `--browser` uses Chromium for browser-based retry.
- Human-verification/Cloudflare pages stop that site's remaining steps.
- Other collected data remains available after a blocked run.
- HTTP 404/410 URLs are not permanently remembered, so they can be retried on later runs.

Scraped files are stored under:

```text
data/raw/data/*.jsonl
```

## Build the search index

Build the database and local backup from Supabase:

```powershell
uv run python -m rag.indexing
```

Build only the local backup:

```powershell
uv run python -m rag.indexing --source local --target local
```

Build from Supabase only:

```powershell
uv run python -m rag.indexing --source database --target database
```

The indexing process:

1. Loads documents from Supabase or local JSONL files.
2. Normalizes HTML entities and whitespace.
3. Removes repeated menu/footer lines.
4. Removes short, duplicate, and error pages.
5. Splits documents into overlapping chunks.
6. Creates dense embeddings when the model is available.
7. Saves the index to Supabase and/or `index/`.

A database chunk count is the number of searchable chunks, not the number of source pages or listings.

## Evaluation

The default evaluation is a smoke test generated from page titles:

```powershell
uv run python -m rag.evaluation
```

It reports:

- **MRR**: mean reciprocal rank.
- **Hit@1**: percentage of correct URLs in the first result.
- **Hit@3**: percentage in the first three results.
- **Hit@6**: percentage in the first six results.

For a reliable evaluation, create `data/eval_set.json` with 20–40 real questions:

```json
[
  {
    "question": "What is the price of Shams Riyadh?",
    "expected_urls": ["https://wasalt.sa/project/..."],
    "expected_terms": ["Shams", "Riyadh"]
  },
  {
    "question": "Tell me about an apartment with 3 bedrooms",
    "expected_urls": ["https://wasalt.sa/en/property/sale/..."] ,
    "expected_terms": ["3 Bedrooms", "Apartment"]
  }
]
```

Run it explicitly:

```powershell
uv run python -m rag.evaluation --set data/eval_set.json
```

Do not use smoke-test output as a replacement for real user questions. Generated title questions are easy and mainly check basic retrieval connectivity.

Check full answers with an API key/model configured:

```powershell
uv run python -m rag.evaluation --generate 10
uv run python -m rag.evaluation --set data/eval_set.json --generate 10
```

## Run locally
  
Start the API and interface:

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 7860
```

Open:

```text
http://127.0.0.1:7860/
http://127.0.0.1:7860/health
http://127.0.0.1:7860/docs
```

The health endpoint reports:

- API status.
- Database or local index backend.
- Chunk count.
- Vector-search availability.
- Data snapshot date.
- Number of configured providers.

Example:

```powershell
Invoke-RestMethod http://127.0.0.1:7860/health
```

## Chat API

Send a chat request:

```powershell
$body = @{ 
  messages = @(@{ role = "user"; content = "What projects are available in Riyadh?" })
  api_key = "sk-or-v1-your-key"
  model = "openrouter/free"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -ContentType "application/json" -Body $body -Uri "http://127.0.0.1:7860/api/chat"
```

List discovered free models:

```powershell
Invoke-RestMethod "http://127.0.0.1:7860/api/models"
```

The browser can store an API key and selected model in `localStorage`. It can also remove the saved key without restarting the server.

Never send secrets to the browser in a public demo if the deployment is meant to hide the key; server-side keys are safer. For the included public UI, use a dedicated deployment key and monitor usage.

## Testing

Run all local tests:

```powershell
uv run pytest
```

Run database tests with a dedicated test database:

```powershell
$env:TEST_DATABASE_URL="postgresql://..."
uv run pytest
```

Remove the environment variable afterward:

```powershell
Remove-Item Env:TEST_DATABASE_URL
```

## Docker

Build locally:

```powershell
docker build -t darglobal-chatbot:latest .
```

Run with environment variables:

```powershell
Copy-Item .env.example .env
docker run --env-file .env -p 7860:7860 darglobal-chatbot:latest
```

Open:

```text
http://127.0.0.1:7860/
http://127.0.0.1:7860/health
```

Useful Docker commands:

```powershell
docker ps
docker logs -f CONTAINER_ID
docker stop CONTAINER_ID
docker rm CONTAINER_ID
```

The Docker build:

- Installs project dependencies.
- Copies `src/` and `data/`.
- Downloads the embedding model.
- Builds a local backup index from local JSONL data.
- Runs the FastAPI server as a non-root user.

## Hugging Face Spaces deployment

1. Create a Hugging Face account.
2. Create a new Space.
3. Select **Docker** as the SDK.
4. Set the exposed port to `7860` if required by the Space configuration.
5. Push this project to the Space Git repository.

### PowerShell Git setup

```powershell
git init
git branch -M main
git add .
git commit -m "Initial DarGlobal and Wasalt chatbot"
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

Add the Hugging Face remote:

```powershell
git remote add hf https://huggingface.co/spaces/USERNAME/SPACE-NAME
git push hf main
```

Or create the Space and push through Hugging Face Git instructions.

### Hugging Face secrets

Add secrets under **Settings → Variables and secrets**:

```text
DATABASE_URL
OPENROUTER_API_KEY
OPENROUTER_API_KEYS
```

Optional:

```text
FALLBACK_BASE_URL
FALLBACK_API_KEY
FALLBACK_MODELS
```

The committed repository should not contain `.env` or secrets.

After deployment, verify:

```text
https://USERNAME-SPACE-NAME.hf.space/
https://USERNAME-SPACE-NAME.hf.space/health
https://USERNAME-SPACE-NAME.hf.space/docs
```

A healthy response should show `status: ok` and an available `database` or `local` index.

## Model behavior

The model provider:

1. Uses a selected UI model if provided.
2. Otherwise tries configured OpenRouter models.
3. Discovers free OpenRouter text models when enabled.
4. Moves exhausted or invalid keys to a cooldown.
5. Tries backup keys and the optional fallback provider.

No answer is invented when context is missing. The system prompt tells the model to say that information is unavailable and to recommend confirming prices or availability with the seller.

## Troubleshooting

### `No search index found`

Run:

```powershell
uv run python -m rag.indexing --source local --target local
```

Or provide `DATABASE_URL` and run the normal index command.

### `No API key configured`

Set `OPENROUTER_API_KEY` in `.env`, or enter a key in the chat settings panel.

### Database unavailable

The app tries to load the Supabase index first and the local backup second. Verify:

- The session-pooler URL.
- The database password.
- Network access.
- IPv4 compatibility.
- Supabase permissions.

### Embedding model unavailable

The app can continue with BM25-only retrieval. To restore dense retrieval, verify network access and FastEmbed model cache availability.

### Wasalt returns a human-verification page

Wait, reduce concurrency, and rerun slowly:

```powershell
uv run python scripts/scrape.py listings --n 2000 --lang both --browser --delay 8
```

The run remains resumable because saved JSONL rows are not refetched.

### Arabic text display issue

Set PowerShell to UTF-8 when printing evaluation or scraper output:

```powershell
chcp 65001
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING="utf-8"
```

## Security checklist

- Do not commit `.env`.
- Do not commit Supabase passwords or API keys.
- Use dedicated deployment API keys with spending limits.
- Prefer Supabase session-pooler connections.
- Add secrets only to Hugging Face or another deployment platform.
- Monitor OpenRouter usage and key cooldown behavior.
- Respect robots.txt and the source websites' terms and access limits.

## License and data notice

Scraped public pages are used to answer questions about the sources. Data and availability can change. The application should remind users to confirm prices and availability with the relevant seller or developer.
