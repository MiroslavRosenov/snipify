<h1 align="center">Snipify</h1>

<p align="center">
  <strong>Make every link count.</strong><br />
  A fast, free, and secure URL shortener — shorten, share, and manage your links in one place.
</p>

---

## About

**Snipify** is a full-stack URL shortening service in the spirit of [Bitly](https://bitly.com) and [TinyURL](https://tinyurl.com), with a complete backend **and** frontend.

> 👀 This started as a learning project for **FastAPI** with **SQLAlchemy**, and grew into a complete, self-hostable URL shortener. The goal has always been to build the whole thing end to end — not just an API, but the accounts, emails, and polished web UI that make a real product.

## Features

- 🔗 **Link shortening** — turn long URLs into short, shareable aliases with instant redirects.
- 👤 **Accounts** — register, log in, and manage your profile.
- 📊 **Link dashboard** — every link you've created in one paginated view.
- 🔐 **Secure auth** — cookie-based JWT with short-lived access tokens, rotating refresh tokens, and Argon2 password hashing.
- ✉️ **Transactional email** — account activation, password reset, and deactivation notices via SMTP.
- 🔁 **Password reset & account activation** — secure, single-use, expiring tokens.
- 🌗 **Light & dark mode** — a responsive Jinja2 + Tailwind UI with no-flash theme switching.
- 🩺 **Self-hostable** — fully open source; run your own instance.

## Tech Stack

| Layer        | Technology                                            |
| ------------ | ----------------------------------------------------- |
| **Backend**  | [FastAPI](https://fastapi.tiangolo.com/) (async)      |
| **Database** | PostgreSQL via [SQLAlchemy](https://www.sqlalchemy.org/) (async) + [asyncpg](https://github.com/MagicStack/asyncpg) |
| **Auth**     | [PyJWT](https://pyjwt.readthedocs.io/) + [pwdlib](https://frankie567.github.io/pwdlib/) (Argon2) |
| **Frontend** | [Jinja2](https://jinja.palletsprojects.com/) templates + [Tailwind CSS](https://tailwindcss.com/) (compiled locally) |
| **Server**   | [Uvicorn](https://www.uvicorn.org/)                   |
| **Tooling**  | [uv](https://docs.astral.sh/uv/), [Ruff](https://docs.astral.sh/ruff/), [pre-commit](https://pre-commit.com/) |

## Getting Started

### Prerequisites

- Python **3.12+**
- A running **PostgreSQL** database
- [uv](https://docs.astral.sh/uv/) for dependency management

### 1. Install dependencies

```bash
uv sync
```

### 2. Set up the database

Create a database and apply the schema:

```bash
psql "$DATABASE_URL" -f schema.sql
```

### 3. Configure environment

Snipify reads configuration from the environment (or a `.env` file). Create a `.env` in the project root:

```dotenv
# Core
ENVIRONMENT=local                       # local | dev | production
DATABASE_URL=postgresql+asyncpg://db_user:db_password@localhost:5432/your_database

# Auth
SECRET_KEY=replace-with-a-long-random-secret   # e.g. `openssl rand -hex 32`
ALGORITHM=HS256
MAX_SESIONS_PER_USER=3                  # concurrent refresh tokens per user

# SMTP (optional — email features are disabled if unset)
SMTP_SERVER=smtp.example.com
SMTP_PORT=587
SMTP_LOGIN=smtp-username
SMTP_PASSWORD=smtp-password
SMTP_USE_SSL=false
SMTP_FROM_NAME=Your App Name
SMTP_FROM_EMAIL=no-reply@example.com

# Contact & legal (shown in the UI and policy pages)
CONTACT_EMAIL=contact@example.com
LEGAL_EFFECTIVE_DATE=1 January 2025
LEGAL_GOVERNING_LAW=Your Country
```

> ℹ️ If SMTP is not configured, the app still runs — account activation and password-reset emails are simply skipped.

### 4. Build the frontend CSS

Tailwind is compiled locally from [`app/static/css/input.css`](app/static/css/input.css):

```bash
uv run tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
```

Add `--watch` during development to rebuild on changes.

### 5. Run the app

```bash
uv run python main.py
```

The app starts on [http://localhost:8000](http://localhost:8000). In `local`/`dev` environments auto-reload and debug mode are enabled automatically.

## Project Structure

```
app/
├── app.py              # FastAPI app, middleware, exception handlers
├── config.py           # Environment-driven configuration
├── logging.py          # Loguru setup
├── smtp_client.py      # Async SMTP client + Jinja email templates
├── utils.py            # Helpers (alias generation, error pages, validation)
├── api/routers/
│   ├── pages.py        # HTML page routes (index, dashboard, auth pages)
│   ├── redirect.py     # URL creation, listing, and redirect endpoints
│   └── security.py     # Auth: register, login, tokens, password reset
├── models/
│   ├── database.py     # SQLAlchemy models + async session
│   └── requests.py     # Pydantic request/response schemas
├── templates/          # Jinja2 templates (pages + emails)
└── static/             # Favicons + compiled Tailwind CSS
main.py                 # Entrypoint (Uvicorn runner)
schema.sql              # PostgreSQL schema
```

## Development

This project uses [pre-commit](https://pre-commit.com/) with Ruff (lint + format) and Commitizen (commit messages):

```bash
uv run pre-commit install
```

## License

Released under the [MIT License](LICENSE) — free to inspect, modify, contribute to,
or self-host your own instance, with attribution.
