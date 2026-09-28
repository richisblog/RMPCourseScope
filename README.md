# CourseScope

**CourseScope is an independent, open-source search and research interface for UC Davis course and professor reviews.** It provides a bilingual web interface and a read-only JSON API designed for both people and AI agents.

Project: [github.com/richisblog/RMPCourseScope](https://github.com/richisblog/RMPCourseScope) · Live service: [rmp.richis.top](https://rmp.richis.top) · Maintainer: [@richisblog](https://github.com/richisblog)

> CourseScope is not affiliated with, endorsed by, or operated by the University of California, Davis or Rate My Professors. This repository contains software and documentation only. It does not include the SQLite databases, student review records, bulk JSON exports, or production credentials.

## What it does

- Search UC Davis courses and professors in English or Chinese.
- Browse professor profiles, student-submitted reviews, and course links while preserving each review's original course label.
- Search review comments with scoped SQLite FTS5 keyword queries.
- Expose course-level descriptive statistics, activity dates, and confidence-aware course associations through JSON API v1.
- Import official UC Davis catalog metadata into a separate SQLite database and expose titles, units, descriptions, prerequisites, and General Education categories.
- Provide AI-agent prompts, `llms.txt`, and an OpenAPI 3.1 contract.

## API and agent documentation

- OpenAPI contract: [`docs/openapi.json`](docs/openapi.json)
- Agent discovery index: [`docs/llms.txt`](docs/llms.txt)
- English and Chinese prompts: [`docs/agent-prompt-en.txt`](docs/agent-prompt-en.txt), [`docs/agent-prompt-zh.txt`](docs/agent-prompt-zh.txt)
- API URL guide: [`docs/coursescope-url-api.md`](docs/coursescope-url-api.md)
- Statistical methods and database structure: [`docs/course-stats-catalog.md`](docs/course-stats-catalog.md)

Example read-only requests:

```text
GET /api/v1/search?q=ECS%2034&type=course&lang=en
GET /api/v1/courses/ECS50/professors?limit=20
GET /api/v1/courses/ECS50/professors/{professor_id}/stats
GET /api/v1/catalog/courses/ECS50
GET /api/v1/professors/{professor_id}/reviews?course=ECS50&limit=20
GET /api/v1/reviews/search?department=Economics&term=no%20slides&term=powerpoint
```

Course associations can be inferred from review text or other evidence. An association and its confidence are search aids, not proof of enrollment. Ratings and grade entries are voluntarily submitted opinions, not official university statistics.

## Run locally

Requirements: Python 3.12 or newer. The web application uses the Python standard library; Docker deployment uses Gunicorn. Catalog import additionally needs `lxml` (see [`requirements-catalog.txt`](requirements-catalog.txt)).

The private SQLite databases are intentionally not distributed. Provide your own schema-compatible files at `data/coursescope.sqlite`, `data/coursescope-search.sqlite`, and `data/ucdavis-catalog.sqlite`, or set the corresponding environment variables:

```text
COURSESCOPE_DB
COURSESCOPE_SEARCH_DB
COURSESCOPE_CATALOG_DB
```

Then start the server from the repository root:

```sh
PYTHONPATH=src python -m ucd_rmp.web
```

The default server listens on `127.0.0.1:8000`. `/openapi.json`, `/llms.txt`, `/ai-guide`, and `/ai-prompt.txt` provide the API and agent documentation.

To build an independent catalog snapshot from the public UC Davis subject pages:

```sh
python -m pip install -r requirements-catalog.txt
python scripts/build_ucd_catalog.py --db data/ucdavis-catalog.sqlite
```

See [`deploy/README.md`](deploy/README.md) for the generic Docker and reverse-proxy configuration. Do not commit local databases or student review exports.

## Data, privacy, and attribution

The code in this repository is separate from the data used by a live deployment. Review text and professor records are not included. Local database files and export formats are excluded by `.gitignore` and `.dockerignore`.

CourseScope may refer to Rate My Professors as a source of student-submitted opinions and to the UC Davis General Catalog as a source of official course descriptions and categories. These organizations do not sponsor or endorse this project. Review content remains attributable to its original source and is not relicensed by the software license in this repository. Please consult [`NOTICE`](NOTICE) and [`docs/disclaimer.md`](docs/disclaimer.md).

## License

Copyright © 2026 Richisblog. The software and documentation in this repository are licensed under the [Apache License, Version 2.0](LICENSE). The license does not apply to external websites, third-party trademarks, or databases and content that are not included here.

## Citation

If you use CourseScope in research or a project, cite it using [`CITATION.cff`](CITATION.cff) or link to this repository and identify Richisblog as the maintainer.
