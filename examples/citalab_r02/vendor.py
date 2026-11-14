"""Copy the evidence for the N-R02 investigation out of a CitaLab checkout, verbatim.

    python -m examples.citalab_r02.vendor --citalab ../citalab

What is copied (nothing is edited, reformatted or re-encoded):
- the 12 result lines of units N-R02 and N-CF-R02 from results.jsonl, byte for byte,
  into data/results-r02.jsonl;
- the 12 trace files those lines reference;
- the lines of the model re-checks (experiment B) about N-R02;
- the campaign manifest (code hashes, models, temperature);
- the frozen corpus the campaign ran with (agenda fixture, reference time), needed to
  rebuild the initial state when re-executing the evaluated code.

data/sources.json records, for every copied item, where it came from (path, line), its
SHA-256, and the CitaLab commit it was read at. The data is synthetic and published by
CitaLab under CC BY 4.0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

CAMPAIGN = Path("output/evaluation/final-independent-v1")
UNITS = ("N-R02", "N-CF-R02")
DATA = Path(__file__).parent / "data"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines(keepends=True)


def vendor(citalab: Path) -> dict:
    campaign = citalab / CAMPAIGN
    commit = subprocess.run(["git", "-C", str(citalab), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    (DATA / "traces").mkdir(parents=True, exist_ok=True)
    sources: dict = {"citalab_commit": commit, "license": "CC BY 4.0 (CitaLab data)", "results": [],
                     "traces": [], "model_checks": [], "manifest": None, "scenarios": None}

    picked = []
    for number, raw in enumerate(_lines(campaign / "results.jsonl"), 1):
        row = json.loads(raw)
        if row["unit_id"] in UNITS:
            picked.append(raw)
            trace = campaign / Path(row["traces_file"].replace("\\", "/"))
            data = trace.read_bytes()
            (DATA / "traces" / trace.name).write_bytes(data)
            sources["results"].append({"cell_id": row["cell_id"], "source": f"{CAMPAIGN.as_posix()}/results.jsonl",
                                       "line": number, "sha256": sha256(raw.rstrip(b"\r\n"))})
            sources["traces"].append({"cell_id": row["cell_id"], "file": f"traces/{trace.name}",
                                      "source": f"{CAMPAIGN.as_posix()}/traces/{trace.name}", "sha256": sha256(data)})
    (DATA / "results-r02.jsonl").write_bytes(b"".join(picked))

    checks = []
    for number, raw in enumerate(_lines(campaign / "derived" / "comprobaciones-modelos.jsonl"), 1):
        if json.loads(raw).get("unit") in UNITS:
            checks.append(raw)
            sources["model_checks"].append({"source": f"{CAMPAIGN.as_posix()}/derived/comprobaciones-modelos.jsonl",
                                            "line": number, "sha256": sha256(raw.rstrip(b"\r\n"))})
    (DATA / "model-checks-r02.jsonl").write_bytes(b"".join(checks))

    manifest = (campaign / "manifest.json").read_bytes()
    (DATA / "manifest.json").write_bytes(manifest)
    sources["manifest"] = {"source": f"{CAMPAIGN.as_posix()}/manifest.json", "sha256": sha256(manifest)}
    corpus = (campaign / "scenarios.json").read_bytes()
    (DATA / "scenarios.json").write_bytes(corpus)
    sources["scenarios"] = {"source": f"{CAMPAIGN.as_posix()}/scenarios.json", "sha256": sha256(corpus),
                            "matches_manifest": sha256(corpus) == json.loads(manifest)["scenarios_sha256"]}

    # Is the checkout's code the code that was evaluated? (needed to re-execute it)
    evaluated = json.loads(manifest)["sources"]
    differs = [p for p, h in evaluated.items()
               if not (citalab / p).exists() or sha256((citalab / p).read_bytes()) != h]
    sources["code_matches_manifest"] = {"checked": len(evaluated), "differs": differs}

    (DATA / "sources.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                       newline="\n")
    return sources


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--citalab", required=True, type=Path, help="path to a CitaLab checkout")
    s = vendor(p.parse_args().citalab)
    print(f"copied {len(s['results'])} result lines, {len(s['traces'])} traces, {len(s['model_checks'])} model checks "
          f"from CitaLab {s['citalab_commit'][:7]}; code differing from the manifest: "
          f"{s['code_matches_manifest']['differs'] or 'none'}")


if __name__ == "__main__":
    main()
