# Contributing to ReproLab

Thank you for considering a contribution. Bug reports, documentation fixes, new examples and code are all welcome.

## Ground rules

ReproLab is a tool for evidence, so contributions follow a few rules that the code already follows:

1. **Claims need evidence.** A number in the docs comes from a command someone can run. A finding is reproducible from a seed or a stored run.
2. **Limits sit next to claims.** If a feature has an edge it does not cover, say so in [docs/limits.md](docs/limits.md) and where the feature is described.
3. **Simulated stays marked.** Anything injected or derived is labelled as such in the data (`fault.simulated`, `origin`, the evidence rules), not only in prose.
4. **The core has no runtime dependencies.** `src/reprolab` uses the Python standard library and SQLite only. Optional integrations belong in extras or examples.
5. **No personal or real data.** Examples and fixtures are synthetic.

## Development setup

```bash
git clone https://github.com/Andros5/reprolab.git
cd reprolab
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # .venv/bin/python on Linux and macOS
```

## Checks

CI runs these on Ubuntu and Windows with Python 3.11, 3.12 and 3.13. Run them before opening a pull request:

```bash
python -m ruff check src tests examples
python -m pytest -q
python -m examples.portal_demo demo.db
python -m examples.citalab_r02 --no-reexecute --db r02.db
```

Some tests are skipped unless an optional system is installed. For example, the Swiss Job Radar tests need the radar's own environment. A skip is reported, never silent.

## Changes to the event schema

The schema is a contract ([docs/schema.md](docs/schema.md)). A change that alters how events are stored must:

- bump `SCHEMA_VERSION` and add a migration from the previous version;
- keep the frozen fixtures in `tests/fixtures/` loading and replaying;
- add a new frozen fixture for the new version.

The evidence files and fixtures are compared byte for byte, and `.gitattributes` keeps their line endings unchanged. Do not reformat them.

## Pull requests

- Keep each pull request to one topic, and describe what it changes and how you checked it.
- Add or update tests for any change in behaviour.
- Update the docs and add an entry under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).
- Write code, comments and docs in plain English.

## Reporting a bug

Open an issue with the bug report form. The most useful report includes a command that reproduces the problem. A stored run exported with `reprolab export <run> -o run.json` is even better. Remove anything private from it first.

## Code of conduct

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).
