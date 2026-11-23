# ReproLab documentation

## Guides

- [Getting started](getting-started.md): installation, and your first recorded, replayed, reduced and explored failure.
- [Concepts](concepts.md): boundaries, faults, evidence, dependencies, replay, divergence and reduction.
- [The explorer](explorer.md): seeded, coverage-guided search over fault schedules.
- [Regression and reports](regress.md): replaying old failures against new code, and the HTML views.

## Reference

- [Command line](cli.md): every command, option and exit code.
- [Event schema v3](schema.md): the recording format and its migrations.
- [Limits](limits.md): what ReproLab does not claim.
- [Changelog](../CHANGELOG.md)

## Background

- [Architecture](architecture.md): the pieces and how one failure flows through them.
- [Design decisions](design-decisions.md): three choices, their alternatives, and the evidence that they paid off.
- [Measured results](metrics.md): seeded regressions, determinism and instrumentation overhead.
- [Roadmap](roadmap.md)

## Investigations

- [CitaLab N-R02](investigations/citalab-r02.md): a reschedule request that created a new appointment, rebuilt from the logs.
- [Swiss Job Radar](investigations/radar-submit.md): a real submission path under injected faults, without changing it.

## Presenting the project

- [Pitch](interview/pitch.md): the project in 30 seconds and in 2 minutes.
- [Demo script](interview/demo-script.md): a narrated live demo of about 3 minutes.
- [Demo video source](../video/README.md): the 101-second motion piece, built from real runs.
