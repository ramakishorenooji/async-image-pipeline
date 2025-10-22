# ThumbForge

ThumbForge is an async image processing pipeline built with FastAPI. Clients submit image URLs; the service queues the work, resizes the image into a thumbnail, extracts metadata, stores the results, and exposes APIs to monitor and retrieve processed jobs.

## Features

- **FastAPI + async I/O** for low-latency job ingestion and status retrieval.
- **Redis-backed FIFO queue** feeding a dedicated worker process.
- **PostgreSQL persistence** for job tracking, metadata, and idempotency checks.
- **ProcessPoolExecutor** centered worker to offload CPU-bound image thumbnailing.
- **Docker Compose** environment bundling API, worker, Postgres, and Redis services.

## Architecture Overview

1. **API (`app/main.py`)** accepts jobs, persists metadata, and pushes identifiers onto a Redis list.
2. **Worker (`worker/main.py`)** blocks on Redis, downloads the image via `aiohttp`, resizes it inside a process pool using Pillow, and updates job records.
3. **Storage** writes thumbnails to `storage/thumbnails` (shared volume in Docker).
4. **Dependency Injection** in FastAPI supplies database sessions, Redis clients, and settings.

## API Endpoints (`/v1` prefix)

| Method | Path                         | Description                                                                    |
| ------ | ---------------------------- | ------------------------------------------------------------------------------ |
| `POST` | `/images`                    | Submit an image URL for processing. Returns `202 Accepted` and the job record. |
| `GET`  | `/images`                    | List jobs with pagination and optional filters (status, created_at range).     |
| `GET`  | `/images/{job_id}`           | Retrieve a single job by ID.                                                   |
| `GET`  | `/images/{job_id}/thumbnail` | Download the generated thumbnail once available.                               |
| `GET`  | `/metrics`                   | Aggregate counts per job status.                                               |
| `GET`  | `/healthz`                   | Basic health probe.                                                            |

## Running Locally (Docker Compose)

```powershell
# Build images and start the stack
docker compose up --build

# Initialize database schema if needed
docker compose exec api python -m scripts.init_db
```

Once running:

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- Redis: localhost:6379
- Postgres: localhost:5432 (`thumbforge` / `thumbforge`)

## Local Development (without Docker)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.init_db
uvicorn app.main:app --reload
python -m worker.main  # in a separate terminal
```

## Configuration

Environment variables use the `THUMBFORGE_` prefix (see `.env`). Key settings:

- `THUMBFORGE_DATABASE_URL`: Async SQLAlchemy DSN (default points to Docker Postgres).
- `THUMBFORGE_REDIS_URL`: Redis connection string.
- `THUMBFORGE_STORAGE_PATH`: Where thumbnails are stored.
- `THUMBFORGE_QUEUE_NAME`: Redis list key for jobs.
- `THUMBFORGE_DUPLICATE_HANDLING`: `allow-retry`, `reuse-completed`, or `reject-active`.
- `THUMBFORGE_THUMBNAIL_SIZE`: Maximum dimension for generated thumbnails.

## Project Structure

```
app/
  api/            # FastAPI routers and dependencies
  core/           # Settings and logging
  db/             # Engine and initialization
  models/         # SQLAlchemy models
  schemas/        # Pydantic schemas
  services/       # Domain logic (job orchestration)
worker/           # Redis-driven consumer
scripts/          # Utility entrypoints (DB init)
storage/          # Thumbnail output directory
```

## Testing

```powershell
pytest
```

## Notes

- Postgres indices are declared on `url_hash`, `status`, and `created_at` for efficient querying.
- The worker stores thumbnails as JPEG files named by job UUID.
- Error messages are captured in the `error` column whenever processing fails.
