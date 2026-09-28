# CourseScope JSON API contract (v1)

CourseScope exposes a read-only JSON API v1 for AI agents and other clients. The host name is not part of the contract: all API paths below begin at the root of whichever HTTPS host serves the app. Clients should read `/openapi.json` for operations, parameters, and response schemas. The website pages serve human visitors and are not an agent data interface.

The deployed site is `https://rmp.richis.top`. For a research workflow and reusable agent prompts, use `/ai-guide?lang=zh` or `/ai-guide?lang=en`. Plain-text prompts are at `/ai-prompt.txt?lang=zh|en`; `/llms.txt` is a short discovery index. An agent needs HTTP request capability to call `/api/v1/...` and parse JSON; Python or Shell is optional. If the environment cannot request the API, state that live verification was unavailable rather than guessing or claiming the service is down.

## Stable identifiers and language

- A professor path uses the numeric Rate My Professors ID stored as `professors.legacy_id`.
- A course path uses `courses.course_key`, for example `CHE2A`. The official display code remains `CHE 002A`. Case, spacing, and zero padding are accepted when resolving input codes, but generated links use the compact key.
- Search input `q` accepts Unicode. Encode it as UTF-8 in a URL query string (`化学2A` becomes `%E5%8C%96%E5%AD%A62A`). `lang=zh` or `lang=en` controls interface labels and localized course display text where available; it does not limit which language can be searched. JSON field names remain English in both modes.
- Chinese subject aliases are an explicit, editable dictionary. The initial dictionary covers common UC Davis subjects and the CHE 002A title. When no Chinese course title is known, the API returns the English catalog title or code rather than inventing a translation. English professor names remain searchable in either interface language; Chinese professor-name aliases can be added later.

## JSON URLs for AI and other clients

| Purpose | URL |
| --- | --- |
| Search courses and professors | `/api/v1/search?q=CHE%202A&limit=20` |
| Search in Chinese | `/api/v1/search?q=%E5%8C%96%E5%AD%A62A&lang=zh` |
| One course | `/api/v1/courses/CHE2A` |
| Instructors linked to one course | `/api/v1/courses/CHE2A/professors?min_confidence=0.8&limit=50` |
| One professor | `/api/v1/professors/{professor_id}` |
| Courses linked to a professor | `/api/v1/professors/{professor_id}/courses?min_confidence=0.8` |
| Reviews, course and date window | `/api/v1/professors/{professor_id}/reviews?course=CHE2A&from=2020-01-01&to=2025-12-31&limit=50` |
| Search original review text across the whole university | `/api/v1/reviews/search?term=Russian&term=accent&limit=20` |
| Search one professor's reviews | `/api/v1/reviews/search?professor_id={professor_id}&term=slides&term=PPT&mode=any` |
| Original full RMP payload | Add `include_raw=1` to the reviews URL |
| API description | `/openapi.json` |

Dates are inclusive UTC calendar dates in `YYYY-MM-DD` format. `course` filters on `review_course_links`, so inferred associations are discoverable. Every review still returns the exact student's `course_raw` alongside all proposed course links, relationship types, and confidence values. `min_confidence` accepts a number from 0 to 1 (default 0); clients seeking only stronger associations may raise it. A relationship or confidence is evidence for search, not proof that the student enrolled in a specific section.

List endpoints cap `limit` at 100. Reviews use an opaque `next_cursor`; pass it as `cursor` for the next page while keeping all other filters unchanged. Results are ordered newest first by review date and ID. If `next_cursor` is null, no further page exists. Invalid filters return HTTP 400 with `{ "error": { "code": "...", "message": "..." } }`; unknown IDs return HTTP 404 in the same shape. API responses are UTF-8 JSON.

The service is read-only against `outputs/uc_davis_rmp_normalized.sqlite`. Source review JSON and original course strings remain intact. The root page links the AI guide and `/openapi.json` so developers can discover the interface.

## Review keyword search for agents

Use `GET /api/v1/reviews/search` with repeated `term` parameters (1–10 terms, at most 80 characters each). Search is global when no scope is supplied; optional `professor_id`, `department`, or both narrow it. Optional `course`, inclusive `from`/`to`, `min_confidence`, `limit` (1–100), and opaque `cursor` work like the review listing. `mode=any` (default) matches any term; `mode=all` requires every term in the same comment. Matching uses SQLite FTS5 token and phrase search over the **original review comment**, not semantic interpretation. `department` is an exact case-insensitive RMP department label, such as `Economics`. A course filter uses existing proposed course links and must be interpreted with the original `course_raw` value.

For a vague question, an agent should expand the user's clue into 5–10 plausible terms or phrases (e.g. `no slides`, `no powerpoint`, `without slides`, `blackboard`, `chalkboard`, `handouts`, `lecture notes`, `PPT`), search globally or add a department scope, inspect returned `professor_matches` (top 20 by hit count), then read `comment`, `matched_terms`, `course_raw`, date and professor identity before narrowing by `professor_id`. Counts are candidate-discovery signals, not relevance scores. Results are newest first and include `total_count` and `next_cursor`. Keep the same filters and pass `next_cursor` as `cursor` to continue. The short `snippet` is navigation help; the full `comment` is the evidence. Negation and references to other instructors need human/AI interpretation: a hit for “slides” can say either “uses slides” or “no slides.” Do not infer gender, fame, or current teaching assignment solely from student reviews.

## Instructor ranking and grade/activity fields

`/api/v1/courses/{course_key}/professors` accepts `sort_by=rating_desc|rating_asc|difficulty_asc|difficulty_desc|reviews_desc|retake_desc|active_first` (default `active_first`, then overall rating descending), plus optional `min_rating` (0–5), `max_difficulty` (0–5), `min_reviews` (integer), and `min_take_again` (percentage 0–100). `min_confidence` continues to determine which inferred course links count. Results include `activity_status` and `last_review_date`; `active` means at least one stored review within the last two calendar years, not a verified teaching assignment. The professor detail endpoint returns the same activity fields.

Each course-linked professor also includes `grade_distribution`, based on the grade text students voluntarily reported in their RMP reviews. It counts letter grades A+ through F, other grades, and missing/declined entries. This is not UC Davis's official class grade distribution and should not be treated as GPA. UC Davis defines official grade points separately; see [Office of the University Registrar grading policies](https://registrar.ucdavis.edu/faculty-staff/faculty/grading-policies).

The FTS/activity sidecar is built with `python scripts/build_review_search_index.py [normalized.sqlite] [coursescope_search.sqlite]`. Rebuild it after importing new reviews, then deploy both SQLite files together. The application mounts both files read-only.

## AI lookup sequence

If the user supplies a professor name instead of a numeric ID, call `/api/v1/search?q=<URL-encoded-name>&type=professor` and select the intended person by department. Then fetch `/api/v1/professors/{professor_id}/reviews?course=CHE2A&from=2020-01-01&to=2025-12-31`. The numeric ID prevents people with the same name from being conflated. To discover a course code, call `/api/v1/search?q=%E6%95%B0%E5%AD%A621A&type=course&lang=zh`. Never silently replace `course_raw` with a normalized guess.

## Local run and future KVM deployment

From the repository root, put `src` on `PYTHONPATH` and run `python -m ucd_rmp.web`; the local development server listens on `127.0.0.1:8000` by default. Set `COURSESCOPE_DB` to an absolute SQLite path if the database is elsewhere. The `file://` preview can show the design but cannot serve the API: visit the HTTP server root to use the working links.

For the KVM, serve `ucd_rmp.web:application` through a production WSGI server and an HTTPS reverse proxy. For example, on Linux after installing Gunicorn, run `PYTHONPATH=src COURSESCOPE_DB=/srv/coursescope/uc_davis_rmp_normalized.sqlite gunicorn 'ucd_rmp.web:application' --bind 127.0.0.1:8000 --workers 4`. Keep the database on local storage, mount it read-only for the app, and point the reverse proxy's public host at the WSGI server. The production domain can change without changing the URL paths. The current Docker/Caddy deployment is documented in `deploy/README.md`.
