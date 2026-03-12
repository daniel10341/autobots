"""Entry point: python -m polymarket_bot"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from polymarket_bot.config import BotConfig
from polymarket_bot.agents.coordinator import CoordinatorAgent


def setup_logging(level: str, log_file: str) -> None:
    """Configure logging for the bot."""
    fmt = "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(level=getattr(logging, level.upper()), format=fmt, datefmt=datefmt, handlers=handlers)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="polymarket-bot",
        description="Polymarket Market Maker Bot — 10-Agent Architecture",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live trading mode (default is dry run)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulation mode: real market data, fake trades with virtual balance",
    )
    parser.add_argument(
        "--sim-balance",
        type=float,
        default=1000.0,
        help="Starting virtual USDC balance for simulation (default: 1000)",
    )
    parser.add_argument(
        "--max-exposure",
        type=float,
        default=None,
        help="Override max total exposure in USDC",
    )
    parser.add_argument(
        "--order-size",
        type=float,
        default=None,
        help="Override default order size in USDC",
    )
    parser.add_argument(
        "--min-profit",
        type=float,
        default=None,
        help="Override minimum profit margin per pair (e.g. 0.02 = 2 cents)",
    )
    parser.add_argument(
        "--max-markets",
        type=int,
        default=None,
        help="Max number of markets to trade simultaneously",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Dashboard web port (default: 8080)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = BotConfig()
    config.dry_run = not args.live
    config.simulate = args.simulate
    config.sim_balance = args.sim_balance
    config.dashboard_port = args.port
    config.log_level = args.log_level

    if args.max_exposure is not None:
        config.trading.max_total_exposure = args.max_exposure
    if args.order_size is not None:
        config.trading.default_order_size = args.order_size
    if args.min_profit is not None:
        config.trading.min_profit_margin = args.min_profit
    if args.max_markets is not None:
        config.trading.max_markets = args.max_markets

    setup_logging(config.log_level, config.log_file)

    logger = logging.getLogger("polymarket_bot")
    logger.info("Starting Polymarket Market Maker Bot...")

    if config.simulate:
        logger.info(f"*** SIMULATION MODE — Virtual ${config.sim_balance:.0f} USDC, real market data ***")
    elif config.dry_run:
        logger.info("*** DRY RUN MODE — No real orders will be placed ***")
    else:
        logger.warning("*** LIVE TRADING MODE — Real money at risk! ***")

    coordinator = CoordinatorAgent(config)

    try:
        asyncio.run(coordinator.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
