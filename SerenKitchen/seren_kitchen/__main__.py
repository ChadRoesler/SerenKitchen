"""Entry point for `python -m seren_kitchen` or the `seren-kitchen` script.

--config / -c like the rest of the family; --describe answers before anything
heavy is imported, so a broken install can still say its own name.
"""
from __future__ import annotations

import argparse
import json
import sys


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main() -> None:
    _force_utf8_stdio()
    if "--describe" in sys.argv[1:]:
        from ._describe import DESCRIBE
        print(json.dumps(DESCRIBE))
        raise SystemExit(0)

    parser = argparse.ArgumentParser(prog="seren_kitchen",
                                     description="SerenKitchen - a fridge per app, and the notes we leave each other.")
    parser.add_argument("--config", "-c", default=None,
                        help="Path to seren-kitchen.yaml (default: $SEREN_KITCHEN_CONFIG, then "
                             "~/seren-kitchen/seren-kitchen.yaml, then built-in defaults).")
    args = parser.parse_args()

    import uvicorn
    from seren_meninges.exposure import enforce_server

    from ._diag import diag
    from .app import create_app
    from .config import load_config

    cfg = load_config(args.config)
    enforce_server(cfg.server, service="seren-kitchen", env_prefix="SEREN_KITCHEN", log=diag)
    app = create_app(cfg)
    diag(f"[seren-kitchen] the kitchen at http://{cfg.host}:{cfg.port}/viewer")
    diag(f"[seren-kitchen] {len(cfg.fridges)} fridges on the wall; sheets kept in {cfg.state_path}")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
