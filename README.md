# 🏡 Homelab Services Dashboard

A unified Streamlit dashboard for interacting with a local **Valkey**, **Kafka**,
**Schema Registry**, **PostgreSQL**, **Hasura** and **S3** stack — monitor, manage
and experiment with core open-source infrastructure from your browser.

Runs under either **Docker** or **Podman**; the `Makefile` detects whichever you have.

---

## ✨ Features

- **Service Health Overview** — live connection status for every service.
- **Valkey** — set/get keys, list all keys, inspect server info.
- **Kafka** — list/create topics, produce and consume messages.
- **Schema Registry** — browse subjects and versions, view schemas, register new
  ones, delete subjects, see the global compatibility level.
- **PostgreSQL** — list databases and tables, insert/query data, run custom SQL.
- **Hasura** — GraphQL console against PostgreSQL.
- **S3 (Floci)** — create/delete buckets, upload/download/delete objects,
  generate presigned URLs, against a local AWS emulator.
- **Grafana** — ships with a pre-provisioned PostgreSQL datasource. Monitored on
  the overview, which links out to Grafana's own UI.

---

## 🚀 Quick start

### Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop) **or**
  [Podman](https://podman.io/) (auto-detected)
- [uv](https://docs.astral.sh/uv/) — only for local development and tests
- Python 3.12 (uv will fetch it if missing)

### Run it

```sh
git clone https://github.com/justinrmiller/homelab.git
cd homelab
cp .env.example .env      # then edit the passwords
make up
```

The dashboard is at <http://localhost:8501>.

```sh
make ps            # service status
make logs          # tail everything
make logs SERVICE=kafka
make down          # stop, keep data
make clean         # stop and DELETE ALL VOLUMES (prompts for confirmation)
```

`make clean` is destructive — it lists exactly what will be lost and requires
you to type `yes`. Use `make clean FORCE=1` to skip the prompt in scripts.

`make help` lists every target. `make engine` shows which container engine was
detected — override with `CONTAINER_ENGINE=docker` or `CONTAINER_ENGINE=podman`.

---

## ⚙️ Configuration

All settings come from environment variables; `docker-compose.yml` reads them
from `.env`. Start from [`.env.example`](.env.example), which documents every
variable.

The ones that matter most:

| Variable | Purpose |
|---|---|
| `BIND_ADDR` | Interface published ports bind to. `127.0.0.1` keeps services off your LAN. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Postgres credentials. |
| `HASURA_GRAPHQL_ADMIN_SECRET` | **Required — no default.** The stack refuses to start without it. |
| `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` | Grafana login. |
| `GRAFANA_PUBLIC_URL` | Where the dashboard's Grafana link points your browser. Defaults to `http://localhost:3000`. |
| `AWS_ENDPOINT_URL` | Floci endpoint. Set automatically inside compose. |

---

## 🔒 Security

This stack ships with development defaults and is intended for a trusted
network. Before running it anywhere else:

- **Set `BIND_ADDR=127.0.0.1`** unless you genuinely need LAN access. The default
  (`0.0.0.0`) publishes Postgres, Kafka, Grafana, Hasura and the S3 emulator to
  every host on your network.
- **`HASURA_GRAPHQL_ADMIN_SECRET` has no default and is required.** Compose
  cannot even parse `docker-compose.yml` without it, so the stack fails fast
  rather than coming up silently insecure — without a secret, anyone who can
  reach port 8080 has full GraphQL read/write access to PostgreSQL. `make up`
  additionally rejects the `change-me` placeholder from `.env.example`.
- **Change `POSTGRES_PASSWORD` and `GF_SECURITY_ADMIN_PASSWORD`.**
- The PostgreSQL page includes a **raw SQL console** by design. Guided controls
  validate table names, but the console runs whatever you type.
- `.env` is gitignored. It was previously committed and has been removed from
  the index; rotate anything that was ever real.

---

## 🧑‍💻 Development

```sh
make install     # sync .venv from uv.lock
make dev         # run the dashboard against localhost services
make test        # pytest with coverage
make cov         # coverage report at htmlcov/index.html
make lint        # ruff check
make fmt         # ruff format
make typecheck   # ty (advisory — ty is pre-1.0)
make check       # everything CI runs
```

Dependencies are managed with **uv** and pinned in `uv.lock`. Add one with
`uv add <package>`, then commit the updated lock file.

### Testing

205 tests at **100% statement and branch coverage**, enforced by
`--cov-fail-under=100` in `pyproject.toml`. No containers required — every
backend is faked.

- `tests/test_config.py`, `test_sql.py`, `test_s3.py`, `test_health.py`,
  `test_clients.py`, `test_schema_registry.py` — unit tests for the pure modules.
- `tests/test_app.py`, `test_app_interactions.py` — full page rendering and
  button handlers via Streamlit's `AppTest` harness.

### Layout

```
homelab/
├── Makefile                 # engine detection + all common commands
├── docker-compose.yml
├── pyproject.toml           # deps, ruff, pytest, coverage, ty config
├── uv.lock
├── .env.example
├── dashboard/
│   ├── app.py               # Streamlit UI
│   ├── config.py            # environment-driven settings
│   ├── clients.py           # client factories
│   ├── health.py            # connection checks
│   ├── s3.py                # S3 operations
│   ├── schema_registry.py   # Schema Registry REST client
│   ├── sql.py               # identifier validation
│   └── Dockerfile
├── grafana/
│   ├── provisioning/        # datasource + dashboard providers
│   └── dashboards/          # dashboard JSON, auto-loaded
├── generators/
│   └── s3_data_generator.py # seed Floci with sample objects
└── tests/
```

The package is named `dashboard`, not `streamlit`, so it cannot shadow the
installed Streamlit package on `sys.path`.

### Seeding sample data

```sh
uv run python generators/s3_data_generator.py --bucket sample-data --objects 100
```

---

## 📦 Services

| Service | Image | Port | Notes |
|---|---|---|---|
| Valkey | `valkey/valkey:9.1.1` | 6379 | Redis-compatible KV store |
| Kafka | `confluentinc/cp-kafka:8.2.2` | 9092, 9094 | KRaft mode, no ZooKeeper |
| Schema Registry | `confluentinc/cp-schema-registry:8.2.2` | 8081 | |
| PostgreSQL | `postgres:18.4` | 5432 | |
| Grafana | `grafana/grafana-oss:13.0.2` | 3000 | Provisioned datasource + dashboard |
| Hasura | `hasura/graphql-engine:v2.49.5-ce` | 8080 | GraphQL over PostgreSQL |
| Floci | `floci/floci:1.5.33` | 4566 | Local AWS emulator (S3) |
| Dashboard | built from `dashboard/Dockerfile` | 8501 | |

### Grafana

Open <http://localhost:3000> and log in with `GF_SECURITY_ADMIN_USER` /
`GF_SECURITY_ADMIN_PASSWORD` from your `.env` (defaults `admin` / `admin`). The
dashboard's overview links there too, and reports Grafana's health alongside the
other services — it polls `/api/health`, which needs no credentials and reports
whether Grafana's own database is healthy, not just whether the port answers.

Grafana has no page of its own in the dashboard: it *is* a UI, so there is
nothing useful for Streamlit to wrap. If you browse the stack from another
machine or through a proxy, set `GRAFANA_PUBLIC_URL` so the link resolves —
the health check keeps using the in-network address either way.

Both the datasource and the dashboards are provisioned from files, so there's
nothing to click through on first boot:

- **Datasource** — `grafana/provisioning/datasources/postgres.yml` defines a
  PostgreSQL datasource (uid `homelab-postgres`) pointing at the `postgres`
  service, credentials interpolated from the environment.
- **Dashboards** — `grafana/provisioning/dashboards/dashboards.yml` loads every
  JSON file in `grafana/dashboards/` into a **Homelab** folder.

Shipped dashboard: **PostgreSQL Overview** (`Dashboards → Homelab`) — connection
count, database size, cache hit ratio, uptime, connection and transaction graphs,
and a per-database table. It reads `pg_stat_database`, so it works against any
PostgreSQL with no extensions required.

To add your own: drop a dashboard JSON into `grafana/dashboards/` and restart
Grafana (`make restart`), or build it in the UI and use *Share → Export* to save
the JSON there. `allowUiUpdates: true` means UI edits stick until the file on
disk changes.

### Using Floci from your own code

Floci emulates the AWS API on a single endpoint, so any AWS SDK works by
overriding the endpoint. It accepts any credentials.

```sh
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
aws s3 mb s3://my-bucket
aws s3 ls
```

Use **path-style addressing** against the container endpoint; virtual-host style
needs Floci's `localhost.floci.io` DNS shim.

---

## ⬆️ Upgrading from the previous stack

- **Qdrant and MongoDB were removed.** Their volumes are left on disk; delete
  them with `docker volume rm homelab_qdrant-data homelab_mongodb-data`
  (or `podman volume rm`).
- **PostgreSQL moved from 17 to 18**, which cannot read a PG17 data directory.
  The stack now uses a **new, empty volume** (`postgres-18-data`); the old
  `postgres-data` volume is untouched. To migrate data, `pg_dump` from a
  temporary `postgres:17` container against the old volume and restore into the
  new one.
- **`streamlit/` is now `dashboard/`** and `requirements.txt` is replaced by
  `pyproject.toml` + `uv.lock`.

---

## 🛠️ Troubleshooting

**`HASURA_GRAPHQL_ADMIN_SECRET` ... required` on any compose command**

That variable has no default, so Compose cannot parse `docker-compose.yml`
without it — including for `down` and `logs`. Create `.env` from
`.env.example` and set a real value; `make up` will do the copy for you.

**A service won't connect**

```sh
make logs SERVICE=<name>
make ps
```

**Podman on macOS: `podman machine` not running**

```sh
podman machine start
```

**Pull fails with `docker-credential-desktop: executable file not found`**

A leftover Docker Desktop credential helper is referenced in
`~/.docker/config.json`. Remove the `credsStore` entry, or run with a clean
config: `DOCKER_CONFIG=$(mktemp -d) make up`.

**Kafka is unhealthy on first boot** — it can take ~30s to elect a controller.
The healthcheck allows for this via `start_period`; give it a moment.

**The dashboard shows services that no longer exist (Qdrant, MongoDB)**

The container is running a stale image. Compose reuses whatever dashboard image
it finds, and the `./dashboard` bind mount does not protect you: an image built
before the `streamlit/` → `dashboard/` rename starts `/app/app.py`, a path the
mount never covers, so the old code runs regardless of what is in your checkout.

`make up` always passes `--build`, so this should not recur. The sidebar footer
shows the running version — if it lags `pyproject.toml`, the image is stale:

```sh
make build && make up
```

Set `NO_BUILD=1` to skip the rebuild when you know the image is current.

**`rootless netns: kill network process: permission denied` on `make down`**

Rootless Podman runs one shared network helper for the stack and kills it when
the last container goes away. Occasionally that kill fails: the helper already
died without Podman clearing its state, and the recorded PID now belongs to
another (often root-owned) process. It is a cleanup failure, not data loss.

`make down` retries once, which normally clears it. If it persists:

```sh
podman machine stop && podman machine start
```

**`make ps` shows nothing but the stack is running**

Rootful and rootless Podman keep completely separate containers, images and
volumes, and a machine can have a connection for each. Starting the stack on
one and inspecting the other looks exactly like the stack vanished. Every target
prints which connection it is using when more than one exists; pin it with:

```sh
CONTAINER_CONNECTION=podman-machine-default make ps
```

---

## 📚 Documentation

- [Valkey](https://valkey.io/docs/)
- [Kafka](https://docs.confluent.io/platform/current/kafka/introduction.html)
- [Schema Registry](https://docs.confluent.io/platform/current/schema-registry/index.html)
- [PostgreSQL](https://www.postgresql.org/docs/18/index.html)
- [Hasura](https://hasura.io/docs/latest/)
- [Floci](https://floci.io/floci/services/s3/)
- [Grafana](https://grafana.com/docs/grafana/latest/)

---

## 📄 License

MIT — see [LICENSE](LICENSE).

## 👤 Author

- [justinrmiller](https://github.com/justinrmiller)
- [claude](https://www.anthropic.com/claude)
