# Decision Lens

Decision Lens is a full-stack decision intelligence chatbot that helps users answer real-world questions like:

- `Should I buy iPhone 17?`
- `Should I switch from Android to iPhone?`
- `Should I wait for the next MacBook Air?`

Instead of relying on generic model output alone, the app scrapes public discussions from Reddit, YouTube, and Quora, structures the raw content, runs multi-stage local LLM analysis with Ollama, and returns a source-backed decision brief with pros, cons, confidence, sentiment split, and source attribution.

## What It Does

- Scrapes multiple public sources for a user query
- Extracts post content plus discussion signals like comments and replies
- Normalizes data into a unified backend schema
- Uses a local Ollama model to extract opinions and aggregate sentiment
- Returns:
  - summary
  - decision score
  - confidence
  - pros
  - cons
  - what-people-say split
  - source breakdown
  - source cards with links and snippets

## Stack

### Backend

- FastAPI
- aiohttp
- BeautifulSoup
- Ollama for local LLM inference

### Frontend

- React
- Vite
- Custom dark-theme UI

## Project Structure

```text
TECH GC/
├── README.md
├── .gitignore
├── backend/
│   ├── .env.example
│   ├── decision_engine.py
│   ├── llm_service.py
│   ├── main.py
│   ├── quora_scraper.py
│   ├── reddit_scraper.py
│   ├── relevance.py
│   ├── requirements.txt
│   ├── schema.py
│   ├── scraper_service.py
│   └── youtube_scraper.py
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── App.css
        ├── index.css
        └── main.jsx
```

## Backend Architecture

- `main.py`
  Exposes the FastAPI app and endpoints.

- `scraper_service.py`
  Orchestrates all source scrapers and combines normalized results.

- `reddit_scraper.py`
  Pulls Reddit posts and top comments relevant to the query.

- `youtube_scraper.py`
  Searches YouTube videos and attempts to gather useful metadata and comments.

- `quora_scraper.py`
  Scrapes Quora-related search results and extracts answer content where possible.

- `llm_service.py`
  Sends structured prompts to Ollama and performs opinion extraction and aggregation.

- `decision_engine.py`
  Coordinates transformation from raw scraped data into processed decision signals.

- `schema.py`
  Defines all request, response, and internal data models.

## Frontend Experience

The frontend is designed as a dark decision workspace:

- large centered hero section
- chatbot-style composer
- source-backed report cards
- general insights data visualization
- score and confidence display
- source list with snippets and links

## API

### `GET /health`

Returns service status and model information.

Example response:

```json
{
  "status": "ok",
  "llm_configured": true,
  "llm_provider": "ollama",
  "model": "qwen2.5:3b"
}
```

### `POST /analyze`

Request:

```json
{
  "query": "Should I buy iPhone 17?",
  "max_results_per_source": 3,
  "use_cache": true
}
```

Response includes:

- decision topic
- summary
- decision score
- confidence
- pros
- cons
- sentiment split
- sources used
- normalized raw data
- processed opinion data

### `POST /analyze/stream`

Streams progress updates while scraping and analyzing.

Useful for the chatbot UI to show intermediate progress.

## Local Setup

## 1. Clone the repo

```bash
git clone <your-repo-url>
cd "TECH GC"
```

## 2. Backend setup

Create a virtual environment if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install backend dependencies:

```bash
cd backend
pip install -r requirements.txt
```

Create `backend/.env` from the example:

```bash
cp .env.example .env
```

Example `.env`:

```env
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:3b
```

## 3. Ollama setup

Install Ollama, then run:

```bash
ollama serve
ollama pull qwen2.5:3b
```

If you want a different model, update `backend/.env` accordingly.

## 4. Frontend setup

```bash
cd ../frontend
npm install
```

## Run the App

Open two terminals.

### Terminal 1: backend

```bash
cd "/Users/vidhanagarwal/Desktop/TECH GC/backend"
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Terminal 2: frontend

```bash
cd "/Users/vidhanagarwal/Desktop/TECH GC/frontend"
npm run dev -- --host 127.0.0.1 --port 5173
```

### Local URLs

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`

## Current Model Choice

The project is currently configured to use:

- `qwen2.5:3b`

This model was chosen to reduce local inference cost and memory usage compared to larger Ollama models.

## Notes on Scraping

- The scrapers target public pages only
- Results depend on platform response behavior and public availability
- Some sources may return partial or noisy data
- YouTube and Quora extraction quality can vary more than Reddit

## Known Limitations

- Local inference can still be slow for multi-source analysis
- Some scraped discussions may still include noisy or weakly relevant opinions
- YouTube comments are less reliable than Reddit comments in the current setup
- Quora HTML structure can change and affect extraction

## Future Improvements

- Faster preprocessing and ranking before LLM calls
- Better relevance filtering for noisy search results
- Stronger source-specific parsing
- Caching and persistence
- User persona filtering
- Better comparative analysis for `X vs Y` questions

## Git Safety

Sensitive files are excluded from Git:

- `backend/.env`
- `.venv/`
- `frontend/node_modules/`
- frontend build output

Do not commit secrets into the repository.

## Suggested Demo Query

```text
Should I buy iPhone 17?
```

This query works well to test:

- Reddit scraping
- opinion extraction
- pros/cons aggregation
- source attribution
- frontend visualization
