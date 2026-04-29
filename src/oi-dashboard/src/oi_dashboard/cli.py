"""CLI for running the oi-dashboard server."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .dashboard import run_dashboard, DEFAULT_HOST, DEFAULT_API_PORT, DEFAULT_DASHBOARD_PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Oi Dashboard — Real-time web dashboard for oi-gateway"
    )
    parser.add_argument(
        "--api-url",
        default=f"http://{DEFAULT_HOST}:{DEFAULT_API_PORT}",
        help=f"Base URL of oi-gateway API (default: http://{DEFAULT_HOST}:{DEFAULT_API_PORT})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Dashboard bind address (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DASHBOARD_PORT,
        help=f"Dashboard HTTP port (default: {DEFAULT_DASHBOARD_PORT})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"Starting Oi Dashboard...")
    print(f"  API: {args.api_url}")
    print(f"  Dashboard: http://{args.host}:{args.port}")
    print()
    print("Dashboard will be available at the URL above")
    print("Press Ctrl+C to stop")
    print()

    try:
        asyncio.run(run_dashboard(
            api_base_url=args.api_url,
            host=args.host,
            port=args.port,
        ))
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
