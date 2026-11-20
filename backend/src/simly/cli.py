"""``simly`` command: run the web app, or a study from a JSON/YAML spec."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simly")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s = sub.add_parser("run", help="run a study spec (JSON) and print the results summary")
    s.add_argument("spec")
    s.add_argument("--convergence", action="store_true")
    s.add_argument("-o", "--out", default="runs/cli")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("simly.api:app", host=args.host, port=args.port)
        return 0

    from .convergence import run_convergence
    from .spec import parse_spec
    from .study import run_study

    spec = parse_spec(json.loads(Path(args.spec).read_text()))
    result = (run_convergence if args.convergence else run_study)(spec, Path(args.out)).to_dict()
    result.pop("display")
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
