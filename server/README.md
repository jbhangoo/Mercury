# Mercury

FastAPI backend for the Mercury imagery client. It proxies Mercury Trek
tiles through `/api/mercury-tile` and returns XRS details for clicked
coordinates through `/api/xrs`, using observations loaded into PostgreSQL.

## Technologies

### Backend
PostgreSQL with PostGIS and SQLAlchemy Core (psycopg 3 driver)

### Server
Python
FastAPI

### Client
TypeScript
Deck.gl and Mercury Trek imagery

### Deployment

This was built using uv, Docker and uvicorn in development

## How to set up data

### Create PostGIS database

- Install PostgreSQL
- Create `mercury` database
- Create PostGIS extension in database

### Load with initial data

Load the XRS calibrated data with `database/CDR_Loader.py`. The `/api/xrs`
endpoint can return spatial results after footprint polygons have been loaded
into the `xrs.footprint` column.

#### Messenger XRS

To download bulk files via curl, wget, or Python scripts:

    XRS Calibrated Data (CDR):
    [https://pds-geosciences.wustl.edu/messenger/mess-m-xrs-3-cdr-v1/](https://pds-geosciences.wustl.edu/messenger/mess-m-xrs-3-cdr-v1/)

    XRS Footprints & Map Products (RDR/DDR):
    [https://pds-geosciences.wustl.edu/messenger/mess-m-xrs-5-rdr-v1/](https://pds-geosciences.wustl.edu/messenger/mess-m-xrs-5-rdr-v1/)

Alternatively, the ODE website has a UI to access the PDS directory trees interactively. You can fill a "cart" then download datasets of interest.

#### Bepicolombo
XRS data will get updated as the mission progresses
but a bulk loader should be built for existing data or data from other sources

## How Client runs

The client requests imagery tiles through the server and sends clicked
latitude/longitude coordinates to `/api/xrs`. The endpoint returns the
observations whose loaded `footprint` covers that point in Mercury's
project SRID 910001. Records without footprints are not spatially matched.
The response contains an `observations` array of database-backed CDR fields
and spectra, plus `has_more`; `limit` defaults to 100 and can be set from 1
to 500. If no footprints cover a point, the array is empty.

## Plan Idea

1. Fetch XRS DDRs: Download the DDR archive from the PDS via ODE

2. Geolocate via SPICE: Create SPICE transformation scripts, convert the observation timestamps and spacecraft/boresight state vectors (using the MESSENGER FK and IK kernels) into surface footprints/polygons on the Mercury ellipsoid (IAU_MERCURY).

3. Filter by Solar Flare State: Keep only measurements taken during active solar X-ray flares (when X-ray fluorescence signal-to-noise ratio is sufficiently high).

4. Aggregate to Spatial Index: Bin the resulting elemental ratio data points into your target coordinate system or spatial spatial grid.

## Layout

```
Mercury/server
├── main.py                  # ASGI app and dev entry point — `python main.py`
├── run-dev.bat              # Windows dev launcher (runs main.py)
├── run-prod.sh              # Uvicorn launcher — used locally and inside the container
├── Dockerfile
├── .dockerignore
├── requirements.txt          # Python dependencies, including SQLAlchemy and psycopg 3
├── .env.example             # copy to .env when you need real config
└── app/
   ├── __init__.py          # FastAPI app factory, CORS setup
    ├── config.py            # env-var-backed settings
    ├── database.py          # shared SQLAlchemy engine access
    └── routes/
      ├── __init__.py       # registers routers
      ├── xrs.py             # GET /api/xrs?lon=<float>&lat=<float>
      └── tile.py            # GET /api/mercury-tile?west=...&south=...&east=...&north=...
```

## Setting this up in PyCharm

1. **Open the folder**: `File → Open...` and point it at `Mercury/`
   (open the folder itself, not a parent directory — PyCharm treats the
   opened root as the project root for import resolution).
2. **Create the interpreter**: PyCharm will usually prompt you when it
   sees `requirements.txt`. If not: `Settings → Project → Python
   Interpreter → Add Interpreter → Add Local Interpreter → New
   Virtualenv Environment`. Base it on Python 3.11+.
3. **Install dependencies**: once the interpreter is set, PyCharm shows a
   banner offering to install from `requirements.txt` — accept it, or run
   `pip install -r requirements.txt` in the built-in terminal.
4. **Create a Run Configuration**: `Run → Edit Configurations → + → Python`.
    - Script path: `main.py`
    - Working directory: the `server/` directory
5. **Run it**: green triangle, or `Shift+F10`. You should see Uvicorn
   listening on `http://localhost:8000`, matching `PYTHON_API_BASE` in
   `app.ts`.
6. **Enable CORS during frontend dev**: already handled — `app/__init__.py`
   applies FastAPI CORS middleware to the API, defaulting to
   allow any origin (`CORS_ORIGINS=*`). Tighten this via `.env` once you
   know what origin your frontend dev server actually runs on.

## Running it

**Dev (Windows, now):**

```
run-dev.bat
```

This runs `main.py` in a uv virtual environment, which starts Uvicorn with
auto-reload enabled. This is for development and debugging.

**Prod-style, run locally (optional):**

```
run-prod.sh
```

(Git Bash / WSL on Windows, or natively on Linux/macOS.) This runs the
same ASGI app (`main:app`) under Uvicorn without code reload, for
production-like behavior.

**Prod (container):**

```
docker build -t mercury .
docker run -p 8000:8000 mercury
```

The image installs `requirements.txt`, copies the app, and runs
`run-prod.sh` as its `CMD` — the same Uvicorn command and `main:app`
target. Dev, local prod-testing, and the container all ultimately run
the exact same `app` object; only *how* it's served changes.

## Verifying it works

With the server running:

```bash
curl http://localhost:8000/api/health
curl "http://localhost:8000/api/xrs?lon=83.25&lat=-74.875"
curl "http://localhost:8000/api/mercury-tile?west=-180&south=-90&east=0&north=0"
```

The Vite client uses these endpoints directly when displaying the map and
requesting details for a clicked coordinate.

## Docker Compose

From the repository root, start the client, API, and PostGIS database with:

```bash
docker compose -f docker/compose.yaml --project-directory . up --build
```

Open the client at `http://localhost:8080`; the API is also available at
`http://localhost:8000`, and Postgres is published on port `5433` by default.
The database initializes PostGIS and the `xrs` table on its first start. Set
`MERCURY_DB_NAME`, `MERCURY_DB_USER`, `MERCURY_DB_PASSWORD`, or
`MERCURY_DB_PUBLISHED_PORT` in the environment or the root `.env` to override
the local-development defaults. Change the default password before using this
stack outside local development.

Stop the stack with `docker compose -f docker/compose.yaml --project-directory . down`.
The database volume is retained; adding `-v` also deletes its data.

## PostGIS data access

The database layer uses SQLAlchemy Core with the psycopg 3 driver. Copy
`.env.example` to `.env` and set `DATABASE_URL`.

The XRS `footprint` column should contain polygons in SRID 910001. The GiST
index allows PostGIS to apply a spatial filter before returning observations.

## Operational notes

- **No auth or rate limiting** is configured on the API endpoints; revisit this before
   exposing the server beyond local development.
