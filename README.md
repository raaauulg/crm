# consultoria-crm

Local-first web CRM for a one-person AI consultancy: **FastAPI + HTMX + SQLite**, with an **MCP server** so an AI assistant can query and update the pipeline in plain language.

It tracks **prospects** (from lead to closing) and **clients** (contracts, monthly fees / MRR, invoices and payments). The UI is in Spanish; the code is in English.

> This repository contains **no real customer data**. Everything under the demo loader is fictional.

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is downloaded by uv if missing.

```bash
uv sync                          # install dependencies
uv run alembic upgrade head      # create / migrate the SQLite database (data/crm.db)
uv run crm crear-usuario raul    # create a login user (asks for the password)
uv run crm demo                  # optional: load fictional demo data
uv run crm serve                 # http://127.0.0.1:8000
```

Configuration comes from environment variables or a `.env` file (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | random per run | Signs the session cookie. Set it, or sessions are lost on restart. |
| `CRM_DB_PATH` | `data/crm.db` | SQLite database file. |
| `CRM_HOST` / `CRM_PORT` | `127.0.0.1` / `8000` | Where the web app listens. |
| `CRM_SECURE_COOKIES` | `false` | Set to `true` behind HTTPS. |
| `CRM_MCP_TOKEN` | – | Enables the MCP server over HTTP at `/mcp` (bearer token, ≥ 32 chars). Unset = disabled. |
| `CRM_VAULT_PATH` | – | Obsidian vault, only for `crm exportar-obsidian`. |

## Features

- Dashboard with two tabs: **prospects** (count per stage, € in play, overdue and upcoming follow-ups, weekly interactions) and **clients** (MRR, invoiced this month / year, pending and overdue receivables).
- Company table with live filters (HTMX) and sortable columns; company page with contacts, notes, interaction history, stage change and next step.
- Charts (Chart.js): stage funnel, MRR and invoiced revenue per month.
- Kanban of open prospects with one-click stage changes.
- Clients: convert a prospect into a client with its first contract, contracts and cancellations, invoice **records** (the CRM does not issue invoices) and payments, editable service catalog.
- Login with argon2 password hashes, signed `HttpOnly` / `SameSite=Lax` session cookie and CSRF tokens on every form.
- **MCP server** (stdio, `crm-mcp`, registered in `.mcp.json`): search companies, view a company, next steps, pipeline and client summaries; create companies, log interactions, change stages and set next steps. Writes are attributed to `mcp`; nothing can be deleted or sent.
- `crm importar leads.csv [--dry-run]`: CSV import with header synonyms, `--columna field=Header` overrides and duplicate detection (accent/case-insensitive).
- `crm exportar-obsidian [--dry-run]`: writes a summary table into an Obsidian note, only between `<!-- crm:resumen:inicio -->` and `<!-- crm:resumen:fin -->`, atomically.
- Money stored as integer cents; dates in Europe/Madrid; Spanish formatting (`1.700,00 €`, `07/10/2026`).

## Architecture

```
models (SQLAlchemy 2.0)  →  services (all business logic)  →  web (FastAPI + Jinja2 + HTMX)
                                                         →  cli (Typer)
                                                         →  mcp (stdio server)
```

The web app, the CLI and the MCP server never touch the database directly: they all go through `crm.services`, so business rules are tested once. See `docs/GUIA.md` (Spanish) for a guided tour.

## Deployment (optional)

A `Dockerfile` is included. The image listens on `0.0.0.0:8000`, stores SQLite in `/data` (mount a persistent volume there) and runs migrations on start. With `CRM_MCP_TOKEN` set, the same MCP tools are served over Streamable HTTP at `/mcp`, so an MCP client can reach the deployed database:

```bash
claude mcp add --transport http crm-remote https://<host>/mcp --header "Authorization: Bearer <token>"
```

Run a **single replica**: SQLite on a network volume supports only one writer. Step-by-step guide for Azure Container Apps (in Spanish): `docs/DESPLIEGUE_AZURE.md`.

## Development

```bash
uv run pytest            # tests (temporary SQLite databases, never real data)
uv run ruff check .      # lint
uv run ruff format .     # format
```

Tailwind CSS, HTMX and Chart.js are loaded from a CDN (no Node build step). For production they should be vendored locally.
