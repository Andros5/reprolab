# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/). The event schema has its own version, which is described in [docs/schema.md](docs/schema.md).

## [Unreleased]

## [1.1.0] - 2026-11-24

No change to the event schema (still v3) or to recorded behaviour. Recordings made with 1.0.0 load and replay unchanged.

### Added

- An investigation of the Swiss Job Radar's real `send()`. It uses a 220-line adapter and changes no radar code, and it is backed by 30 tests that run when the radar is installed ([report](docs/investigations/radar-submit.md)).
- `examples/quickstart.py`, a one-file introduction with its own tests.
- Guides: getting started, concepts, the explorer, regression and reports, the CLI reference, limits and the roadmap.
- Community files: contributing guide, code of conduct, security policy, issue and pull request templates, and `CITATION.cff`.
- `reprolab --version` and `reprolab.__version__`.
- Linting with ruff in CI, a build-and-install check of the wheel, and Dependabot for GitHub Actions.
- Package metadata: classifiers, project URLs, an SPDX licence expression and `py.typed`.

### Changed

- The README is rewritten as a project front page. Its detailed sections moved to `docs/`.
- Imports are sorted and the type hints modernised (ruff `I` and `UP`). There are no behaviour changes.

## [1.0.0] - 2026-11-14

The first stable release. The [release page](https://github.com/Andros5/reprolab/releases/tag/v1.0.0) includes the 101-second demo video.

### Added

- **H1. Record and replay.** A `Session` boundary for calls, the clock and random tokens; offline replay with the network disabled; trace-only invariants; and a local portal demo.
- **H2. Schema and reduction.** The versioned event schema (v1 to v3, with migrations on read); the `record`, `replay`, `show`, `list`, `reduce` and `export` commands; and dependency-closed delta debugging anchored to the same violation.
- **H3. Evidence.** Runs reconstructed from another system's logs, citing a file, a JSON pointer and a SHA-256 for every event, plus the CitaLab N-R02 investigation and `diff`.
- **H4. Explorer.** Six simulated fault kinds, including a crash with restart; a bounded, seeded and coverage-guided search over fault schedules; counterexamples reduced by re-execution; and seeded regression metrics.
- **H5. Regression and views.** `regress` (differential replay with re-recording under the same faults) and `html` (self-contained flight-recorder reports).
- The MIT licence, CI on Ubuntu and Windows with Python 3.11 to 3.13, and the demo video's source in `video/`.

[Unreleased]: https://github.com/Andros5/reprolab/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Andros5/reprolab/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Andros5/reprolab/releases/tag/v1.0.0
