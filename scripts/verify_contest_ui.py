"""Own an isolated server for release UI checks and terminate only that child."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.assist_agent import AssistAgent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5015)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Retain previous UI outputs.")
    args.output.mkdir(parents=True)
    base = f"http://127.0.0.1:{args.port}"
    with (args.output / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "-B", "-X", "utf8", "scripts/run_demo.py", "--port", str(args.port), "--isolated"],
            cwd=ROOT, stdout=log, stderr=log,
        )
        try:
            for _ in range(40):
                if server.poll() is not None:
                    raise RuntimeError("Isolated server exited; check server.log.")
                try:
                    with urlopen(base + "/health", timeout=1) as response:
                        health = json.load(response)
                    if health["assistance_revision"] == AssistAgent.prompt_version:
                        break
                except (OSError, ValueError):
                    time.sleep(.5)
            else:
                raise TimeoutError("Isolated server did not become ready.")
            print("Isolated release server ready.", flush=True)
            for name, script in (
                ("pages", "verify_mainline_ui.py"), ("rehearsal", "rehearse_final_demo.py"),
                ("item_issue", "verify_item_issue_ui.py"),
            ):
                result = subprocess.run(
                    [sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts" / script),
                     "--base", base, "--output", str(args.output / name)],
                    cwd=ROOT, timeout=240, capture_output=True, text=True, encoding="utf-8",
                )
                (args.output / f"{name}.log").write_text(
                    result.stdout + result.stderr, encoding="utf-8")
                if result.returncode:
                    raise RuntimeError(f"{name} check failed; read {name}.log.")
                print(f"{name} checks passed.", flush=True)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
            print("Owned isolated server stopped.", flush=True)


if __name__ == "__main__":
    main()
