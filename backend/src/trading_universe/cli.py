"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-universe")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the API server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")

    sub.add_parser("scan", help="Run one scan and print the result")
    sub.add_parser("briefing", help="Print today's briefing")
    sub.add_parser("init-db", help="Create the database schema")

    imp = sub.add_parser("import-disclosures", help="Import a congressional PTR export")
    imp.add_argument("path")
    imp.add_argument("--chamber", choices=["house", "senate"], default="house")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    if args.command == "serve":
        import uvicorn

        from trading_universe.settings import get_settings

        settings = get_settings()
        uvicorn.run(
            "trading_universe.api.app:app",
            host=args.host or settings.api_host,
            port=args.port or settings.api_port,
            reload=args.reload,
        )
        return 0

    if args.command == "init-db":
        from trading_universe.db import init_db

        init_db()
        print("database initialised")
        return 0

    if args.command == "import-disclosures":
        from trading_universe.data.disclosures import (
            HouseDisclosureClient,
            SenateDisclosureClient,
        )
        from trading_universe.db import Repository, init_db

        init_db()
        client = HouseDisclosureClient() if args.chamber == "house" else SenateDisclosureClient()
        transactions = client.load_csv(args.path)
        Repository().save_political(transactions)
        print(f"imported {len(transactions)} {args.chamber} transactions")
        return 0

    from trading_universe.services.platform import get_platform

    platform = get_platform()
    platform.bootstrap()

    if args.command == "scan":
        result = platform.scanner.last_result
        assert result is not None
        print(f"\nRegime: {result.regime.regime.value if result.regime else 'unknown'}")
        if result.recommendation:
            print(f"Strategy of the day: {result.recommendation.primary_strategy} "
                  f"({result.recommendation.confidence:.0%})")
        print(f"Signals: {len(result.signals)}  Executable: {len(result.executable)}\n")
        for signal in result.signals[:20]:
            flag = "OK " if signal.execution.allowed else "BLK"
            print(
                f"  {flag} {signal.ticker:6s} {signal.confidence:3d}  "
                f"{signal.strategy_id:30s} "
                f"{signal.trade.entry:9.2f} / {signal.trade.stop:9.2f} / "
                f"{signal.trade.target:9.2f}  {signal.trade.reward_risk:.2f}R"
            )
        return 0

    if args.command == "briefing":
        import json

        print(json.dumps(platform.briefing(), indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
