# Self-hosting CourseScope

This is a generic deployment example. Replace the example hostname with a domain you control and configure DNS/TLS for your reverse proxy. The repository does not contain CourseScope's review or catalog databases.

## Prepare runtime data

Create a local `data/` directory and place three compatible SQLite files there:

- `coursescope.sqlite`: normalized professors, courses, reviews, course links, and precomputed course statistics.
- `coursescope-search.sqlite`: SQLite FTS5 review-comment index and professor activity dates.
- `ucdavis-catalog.sqlite`: official course metadata snapshot.

The catalog snapshot can be built from public subject-code pages with `scripts/build_ucd_catalog.py`. The RMP review dataset is deliberately not distributed; you must create and maintain that dataset separately and comply with applicable source terms. Ensure the container can read the database files.

## Start the application

From the repository root:

```sh
docker compose -f deploy/compose.yaml up -d --build
```

The service listens on `127.0.0.1:8000`. Configure your reverse proxy to forward the hostname to that address. A Caddy example is provided in [`Caddyfile`](Caddyfile); change `coursescope.example.com` to your own hostname.

Logs and status:

```sh
docker compose -f deploy/compose.yaml logs -f coursescope
docker compose -f deploy/compose.yaml ps
```

To refresh data, build new database files separately, validate them, then replace the files in `data/` and restart the container. Keep private databases, credentials, and local environment files out of version control.
