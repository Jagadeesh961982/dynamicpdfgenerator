# PDF Pipeline API (FastAPI)

HTTP API around the repository PDF pipeline: user accounts, encrypted LLM API keys, per-user default preferences, **render jobs** (PDF or HTML), and **chat** thread storage. Interactive documentation is available at `/docs` when the server is running.

## Prerequisites

- Python 3.10+ (as required by the repo root [`requirements.txt`](../requirements.txt))
- Dependencies: install from the **repository root** (recommended) so the orchestrator and agents resolve:

  ```bash
  pip install -r requirements.txt
  ```

  The FastAPI app also lists [`requirements.txt`](requirements.txt), which extends the root file with `pydantic-settings`.

  Password hashes use the **`bcrypt`** package directly (not PassLib). If you previously installed `passlib`, run `pip uninstall passlib -y` and reinstall from `requirements.txt` so the environment matches.

**Where data lives:** User accounts, jobs metadata, chat, and preferences are stored in the database (default **SQLite** file at `<repo>/data/api.sqlite3`). That is already local on-disk storage; the browser’s `localStorage` cannot replace it for a Python API. To use PostgreSQL or MySQL later, set `DATABASE_URL` in `.env` to a SQLAlchemy URL.

## Configuration

Configuration is loaded from [`app/core/config.py`](app/core/config.py) via `pydantic-settings`. You can copy [`.env.example`](.env.example) to **`fastapi-app/.env`** and adjust values.

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET` | Signing key for Bearer JWT access tokens. **Change in production.** |
| `FERNET_KEY` | Key material for encrypting stored LLM API keys. Required for `/v1/me/keys` to work reliably. |
| `DATABASE_URL` | SQLAlchemy URL. Default: SQLite at `<repo>/data/api.sqlite3`. |
| `STORAGE_ROOT` | Filesystem root for job artifacts. Default: `<repo>/data/storage`. |
| `REPO_ROOT` | Repository root (parent of `fastapi-app/`). Used for imports and defaults. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime (default one week). |
| `CORS_ORIGINS` | Comma-separated allowed browser origins, e.g. `http://localhost:5173,http://127.0.0.1:5173`. Needed when the SPA runs on a different origin than the API. |

Do not commit real secrets. Use a long random `JWT_SECRET` and a proper Fernet key for production.

## Run the API

From the **`fastapi-app`** directory (so `app` is importable):

```bash
cd fastapi-app
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Health: `GET http://127.0.0.1:8000/health`
- OpenAPI UI: `http://127.0.0.1:8000/docs`

### Tests

```bash
cd fastapi-app
pytest app/tests -q
```

## API overview (`/v1`)

All JSON APIs are under the **`/v1`** prefix unless noted.

| Group | Endpoints | Auth |
|-------|-----------|------|
| **Auth** | `POST /v1/auth/register`, `POST /v1/auth/login` | Public |
| **User** | `GET /v1/me` | Bearer |
| **Preferences** | `GET /v1/me/preferences`, `PUT /v1/me/preferences` | Bearer |
| **LLM keys** | `GET/POST /v1/me/keys`, `DELETE /v1/me/keys/{key_id}` | Bearer |
| **Jobs** | `POST /v1/jobs/render-json`, `POST /v1/jobs/render-file`, `GET /v1/jobs`, `GET /v1/jobs/{job_id}`, `GET /v1/jobs/{job_id}/download` | Bearer |
| **Chat** | `POST /v1/chat/threads`, `GET /v1/chat/threads`, `GET/POST /v1/chat/threads/{thread_id}/messages` | Bearer |

Authentication: send `Authorization: Bearer <access_token>` (token from `/v1/auth/login`).

**Render behavior:** `render-json` and `render-file` run the pipeline synchronously and return a **file** (PDF or HTML) on success, not a JSON body. Clients should read the response as a binary blob and inspect `Content-Type`. Job metadata is still persisted; use `GET /v1/jobs` and `GET /v1/jobs/{id}/download` to list and re-download completed outputs.

## Web frontend (Notebook-style UI)

A React + Vite app lives in [`../frontend`](../frontend). It talks to this API (Bearer auth, jobs, preferences, keys, chat).

1. Start the API (see above).
2. In another terminal:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. Open the URL printed by Vite (typically `http://localhost:5173`).

By default, [`frontend/.env`](../frontend/.env) uses an empty `VITE_API_BASE_URL` so the dev server can **proxy** `/v1` and `/health` to `http://127.0.0.1:8000` (see [`frontend/vite.config.ts`](../frontend/vite.config.ts)). For a production build served from another host, set `VITE_API_BASE_URL` to your API base URL (no trailing slash) and ensure `CORS_ORIGINS` on the server includes that UI origin.

## Architecture note

The FastAPI package adds the **repository root** to `sys.path` so the existing pipeline (`orchestrator`, `agents`, `config`) can run inside render endpoints. The database stores users, preferences, credentials, jobs, and chat; generated files live under `STORAGE_ROOT` per job.
