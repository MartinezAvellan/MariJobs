# MariJobs

Telegram bot that searches jobs across 6 sources, evaluates relevance with AI against the user's CV, and presents jobs one by one with a voting system. All data persisted in MongoDB.

> **Personal project** — built for personal use and shared openly for learning purposes. Not intended for commercial use.

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/martinezavellan)

## Creating a Telegram Bot (BotFather)

To run MariJobs, you need to create a Telegram Bot and obtain a bot token.

### 1. Create the Bot

1. Open Telegram and search for **@BotFather**
2. Start the conversation and send:

/start

3. Create a new bot:

/newbot

4. Choose:
   - A name for your bot (e.g., `YourBotName Bot`)
   - A unique username ending with `bot` (e.g., `yourbotname_bot`)

After completing the steps, BotFather will return a **Bot Token**, similar to:

123456789:AAE_xxxxxxxxxxxxxxxxxxxxx

Keep this token secure. Do not share it or commit it to your repository.

---

### 2. Configure the Token

Add the token to your `.env` file:

TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE

Make sure the `.env` file is included in your `.gitignore`.

---

Once configured, start the application and send `/start` to your bot in Telegram.

## Job Sources

- **LinkedIn** (via JobSpy)
- **Indeed** (via JobSpy)
- **Glassdoor** (via JobSpy)
- **Google Jobs** (via JobSpy)
- **Euraxess** (custom scraper, whitelisted users only)
- **IBEC Barcelona** (custom scraper, whitelisted users only)

## How It Works

1. Send `/start` on Telegram
2. Share your contact (phone number) for identification
3. If not whitelisted, provide your OpenRouter API key (or skip to use without AI)
4. Choose the AI model (default: `openai/gpt-4.1-mini`, customizable)
5. Upload your CV as PDF (saved in MongoDB for future searches)
   - Without API key: jobs are shown with description (up to 500 chars) instead of AI analysis
6. Enter search terms separated by comma
7. Select countries via inline keyboard (multi-select)
8. The bot searches in phases (JobSpy first, then Euraxess and IBEC for whitelisted users)
9. Each job is analyzed by AI before being shown (or displayed with description if no AI)
10. For relevant jobs, the AI also suggests a short recruiter outreach message
11. Jobs appear one at a time with voting buttons
12. After voting, you can leave feedback to refine future searches
13. When the queue empties, the next source is fetched (whitelisted) or completion is shown
14. Use `/history` to view all voted jobs, track application stages (applied → screening → interview → offer → closed)

If you already have a saved profile, you can reuse or modify existing data.
If you have pending jobs, the bot resumes where you left off.
API key and model can be changed at any time via `/apikey` and `/model`.

## Phased Search

Search is performed in 3 phases to avoid overloading sources and deliver results faster:

1. **Phase 1 — JobSpy** (LinkedIn, Indeed, Glassdoor, Google): all users
2. **Phase 2 — Euraxess**: whitelisted only, triggered when JobSpy jobs are exhausted
3. **Phase 3 — IBEC Barcelona**: whitelisted only, triggered when Euraxess jobs are exhausted

Each phase appends jobs to the existing queue. Users start reviewing while the next sources wait.

Anti-throttling: configurable delay (`scrape_delay`) between HTTP requests to prevent site blocking.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start (uses saved profile if exists) |
| `/new` | Create profile from scratch |
| `/terms` | Change search terms only |
| `/cv` | Re-upload CV |
| `/apikey` | Change OpenRouter API key |
| `/model` | Change AI model |
| `/interview` | Log interview experience for current job |
| `/history` | View voted jobs and track applications |
| `/back` | Go back to previous step |
| `/status` | View current profile |
| `/skip` | Discard pending jobs |

## Setup

1. Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

2. Set the variables:

```
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
OPENROUTER_API_KEY=your-openrouter-key
MONGO_URI=mongodb://localhost:27017
```

3. Configure countries, whitelist and parameters in `config/marijobs.yml`

### Run Locally

```bash
python -m pip install -r requirements.txt
python -m src.main
```

Requires MongoDB running on `localhost:27017`. If using Docker for MongoDB only, the `docker-compose.override.yml` exposes the port to localhost:

```bash
docker compose up -d mongo
```

### Run with Docker

```bash
docker compose up -d --build
```

Starts MongoDB and the bot automatically. The Docker setup uses dual networking:
- **internal** (bridge, no internet) — MongoDB only, isolated from external access
- **external** (bridge) — bot container, with access to Telegram API and OpenRouter

This ensures MongoDB is never exposed to the internet even without firewall rules.

## Configuration

Edit `config/marijobs.yml`:

- **app**: timezone, job cache duration (db_cache_hours), delay between requests (scrape_delay)
- **mongo**: URI environment variable and database name
- **jobspy**: search sites, available countries, results per term
- **telegram**: bot environment variable names
- **openrouter**: AI model (default, user-customizable), minimum relevance score, phone whitelist

### Available Countries

Portugal, Spain, France, Germany, Netherlands, UK, Ireland, Estonia, Latvia, Lithuania, Sweden, Switzerland, Norway, USA, Brasil, Worldwide. Configurable in `jobspy.country_options`.

### Phone Whitelist

Numbers in `openrouter.whitelisted_phones`:
- Use the default API key and model from `.env`/YAML
- Have access to Euraxess and IBEC as additional sources (phases 2 and 3)

Other users provide their own OpenRouter key and can choose the AI model (default: `openai/gpt-4.1-mini`, accepts any OpenRouter model like `z-ai/glm-4.5-air:free`). They receive jobs from JobSpy only.

### Change API Key and Model Anytime

- `/apikey` — shows current status (masked key), allows changing or removing (disables AI)
- `/model` — shows current model, allows changing to custom or resetting to default
- Whitelisted users cannot change the API key (shared key), but can change the model

### Global Job Pool

Jobs are shared across all users. If user A searches "Java Senior Portugal", user B searching the same terms will find cached jobs from the database without re-scraping. The `found_by` field tracks which users discovered each job (for analytics), but does not restrict access.

### Job Cache

The bot checks MongoDB before searching externally. Jobs found within the last `db_cache_hours` hours (default 48) are reused globally, avoiding duplicate searches. Job deduplication uses the URL as the idempotency key — the same URL is never inserted twice. Jobs the user has already voted on are automatically excluded from new search queues.

### Remote Search Toggle

The country picker includes a "Remote" toggle button. When enabled, JobSpy filters for remote-only positions (`is_remote=True`). Euraxess and IBEC are not affected (they don't support remote filtering).

### Interview Experience (Glassdoor-like)

After voting a job as relevant, users can log their interview experience:
- Salary offered/range and currency
- Interview stages description
- Process rating (1-5 via inline buttons)
- Free-text experience and tips

Other users viewing the same job see the interview count and average rating in the job card. Also accessible via `/interview` command.

### Recruiter Message Suggestion

When AI is enabled and a job scores at or above the minimum relevance score, the AI generates a short 2-3 sentence message the candidate can send to the recruiter. This message is personalized based on the job details and the candidate's CV. It appears in the job card right after the AI verdict, under "Suggested message:". Generated in the same API call as the review (no extra cost or latency). Cached alongside the review in MongoDB.

### Application Tracker

After voting on jobs, use `/history` to view all your voted jobs with a paginated list. For each job you can track your application pipeline:

- **Applied** — You submitted an application
- **Screening** — Resume/profile under review
- **Interview** — Interview stage
- **Offer** — You received an offer
- **Closed (Approved/Rejected)** — Final outcome

Tracking is per-user and persists in MongoDB. Accessible from `/history` or via the "Track application" button after voting a job as relevant.

### Country Filtering

JobSpy uses the selected country as `location` to filter results across all sources (LinkedIn, Indeed, Glassdoor, Google). Euraxess filters by `offer_country` via internal mapping. IBEC is fixed to Barcelona.

### IBEC Barcelona

The IBEC scraper lists all jobs from the main page (up to 5 pages), filters by valid deadline (ignores expired deadlines), and fetches the full description from each job's detail page. Supports date formats with `/` or `-` and variants with "Deadline:" or "Deadline;".

## Structure

```
src/
  main.py                    - Entry point, loads .env, init MongoDB, starts bot
  core/
    config.py                - Pydantic models + YAML config loader
    utils.py                 - Logger with user context
  store/
    mongo.py                 - MongoDB persistence (users, jobs, reviews, searches, queues, votes, feedback, applications)
  services/
    jobspy.py                - JobSpy search (per term x country x site, with delay)
    euraxess.py              - Euraxess scraper (HTML + BeautifulSoup, with delay)
    ibec.py                  - IBEC Barcelona scraper (deadline filter, detail fetch, with delay)
    openrouter.py            - AI job review + recruiter message (CV vs job, per-user API key + model)
    cv_parser.py             - PDF text extraction (pypdf)
  bot/
    handler.py               - Conversational bot (state machine + polling + phased search)
    telegram.py              - Telegram API helpers (messages, keyboards, contact)
    summary.py               - Single job card (AI verdict, recruiter message, or description) and vote buttons
config/
  marijobs.yml               - Main configuration
docker-compose.yml           - App + MongoDB (dual-network: internal + external)
docker-compose.override.yml  - Local dev: exposes MongoDB on 127.0.0.1:27017
Dockerfile                   - Multi-stage build with dependency caching
```

## Docker

Multi-stage build: `builder` stage installs dependencies in `/deps`, final stage copies only what's needed. Optimized layer caching — if only `src/` changes, `pip install` comes from cache. Multi-platform support via `--platform=$BUILDPLATFORM`.

Bot startup is resilient to transient network issues — `set_my_commands` (Telegram command hints registration) is non-fatal and logs a warning if DNS is not yet available.

## Logs

```bash
docker compose logs -f marijobs
```

## Support

If this project was useful to you:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/martinezavellan)

## License

This project is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free to use and share for non-commercial purposes with attribution.
