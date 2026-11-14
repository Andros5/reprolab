# Evidence copied from CitaLab

Verbatim copies from CitaLab's public evaluation campaign `final-independent-v1` (directory `output/evaluation/final-independent-v1` of the CitaLab repository). The files are not edited, reformatted or re-encoded.

| File | Origin |
|---|---|
| `results-r02.jsonl` | The 12 lines of `results.jsonl` for units N-R02 and N-CF-R02 |
| `traces/` | The 12 trace files those lines reference |
| `model-checks-r02.jsonl` | The lines of `derived/comprobaciones-modelos.jsonl` about N-R02 |
| `manifest.json` | The campaign manifest: code hashes, models, temperature |
| `scenarios.json` | The frozen corpus the campaign ran with |
| `sources.json` | Each item's origin path, line and SHA-256, the CitaLab commit, and whether the code matched the manifest |

All data is synthetic. It is published by CitaLab under the [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) licence, and is redistributed here unchanged with that attribution.

Regenerate with `python -m examples.citalab_r02.vendor --citalab <path to CitaLab>`. Git must not convert line endings here (see `.gitattributes`), because every byte is checked against its SHA-256.
