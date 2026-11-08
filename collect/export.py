"""Turns raw runs (runs/<scenario>/) into incidents (incidents/<scenario>/), keeping only scenarios that
reached the expected state. Run on your Mac after collect/run_all.sh:  python3 collect/export.py"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(runs=ROOT / "runs", incidents=ROOT / "incidents"):
    incidents.mkdir(exist_ok=True)
    kept = 0
    for run in sorted(p for p in runs.iterdir() if p.is_dir()):
        label = json.loads((run / "label.json").read_text())
        raw = (run / "ad.json").read_text().strip() if (run / "ad.json").exists() else ""
        ad = json.loads(raw) if raw else []
        ad = ad[0] if isinstance(ad, list) and ad else (ad if isinstance(ad, dict) else {})
        status, code = ad.get("JobStatus"), ad.get("ExitCode", 0)
        ok = (label["expect"] == "held" and status == 5) or \
             (label["expect"] == "completed_nonzero" and status == 4 and code not in (0, None))
        if not ok:
            print(f"SKIP {run.name}: expected {label['expect']}, got JobStatus={status}, ExitCode={code}")
            continue
        dest = incidents / run.name
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir()
        (dest / "ad.json").write_text(json.dumps(ad, indent=1))
        for f in ("job.log", "stdout.txt", "stderr.txt", "label.json"):
            if (run / f).exists():
                shutil.copy(run / f, dest / f)
        kept += 1
    print(f"Kept {kept} incidents in {incidents}")


if __name__ == "__main__":
    main()
