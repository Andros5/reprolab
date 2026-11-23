# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.x | ✅ |

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through GitHub's **[Report a vulnerability](https://github.com/Andros5/reprolab/security/advisories/new)** form, which is in the repository's *Security* tab.

Include what you found, how to reproduce it, and what an attacker could do with it. You should get an answer within a week. Once a fix is ready, the advisory will be published with credit to you, unless you prefer otherwise.

## Things to know

- **Recordings contain what crossed the boundary.** Requests and responses are stored as they were, in SQLite and in exported JSON. If your code sends secrets or personal data through `session.call`, they end up in the recording. Do not share recordings without reviewing them.
- **Targets are Python imports.** `reprolab record`, `replay`, `explore` and `regress` import and run the scenario module you name. Run them only on code you trust.
- **Offline replay blocks sockets in-process.** It is a safeguard for correctness, not a sandbox.
