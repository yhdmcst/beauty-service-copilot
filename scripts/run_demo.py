"""Run the local demo on an explicit loopback port."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.app_upgraded import create_app
from src.api.websocket_handler import socketio
from src.ops.case_store import CaseStore
from evaluation.evaluation_center import FrozenAnnotationAgent


def main() -> None:
    """Start the development service without exposing it on the network."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--isolated", action="store_true",
                        help="Use in-memory records for software verification.")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    app = create_app(
        case_store=CaseStore(":memory:"),
        evaluation_store=FrozenAnnotationAgent(":memory:"),
    ) if args.isolated else create_app()
    socketio.run(
        app, host="127.0.0.1", port=args.port,
        debug=False, use_reloader=False, allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
