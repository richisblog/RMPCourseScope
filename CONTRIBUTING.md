# Contributing

Thanks for considering a contribution to CourseScope.

## Before opening a pull request

- Keep the project independent and do not imply endorsement by UC Davis or Rate My Professors.
- Never submit SQLite databases, student review exports, API credentials, server addresses, or other private deployment data.
- Preserve original review text and original course labels. Normalized course links must remain explainable and must not be presented as enrollment proof.
- Keep API changes documented in `docs/openapi.json` and update the English and Chinese agent guides when behavior or fields change.
- Include a concise explanation of the user-visible behavior and any data-quality implications.

## Development

The web application is in `src/ucd_rmp/`; import and maintenance scripts are in `scripts/`. Runtime data files are supplied separately and are deliberately not tracked. See the README for local setup and deployment notes.

By submitting a contribution, you agree that it may be distributed under the repository's Apache-2.0 license unless a separate written agreement says otherwise.
