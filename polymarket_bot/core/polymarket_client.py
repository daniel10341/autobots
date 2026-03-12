"""Polymarket CLOB API client wrapper."""

import logging
from typing import Any, Optional

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from polymarket_bot.config import PolymarketConfig
from polymarket_bot.core.simulator import SimulatedExchange
from polymarket_bot.models.market import (
    Market,
    Order,
    OrderAction,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    Side,
    Token,
)

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Unified client for Polymarket CLOB and Gamma APIs.

    Wraps py-clob-client and provides methods used by all agents.
    In simulation mode, uses real market data but simulated execution.
    """

    def __init__(self, config: PolymarketConfig, simulate: bool = False, sim_balance: float = 1000.0) -> None:
        self.config = config
        self._clob: Optional[ClobClient] = None
        self._http = httpx.AsyncClient(timeout=30.0)
        self.simulate = simulate
        self.sim_exchange: Optional[SimulatedExchange] = None
        if simulate:
            self.sim_exchange = SimulatedExchange(starting_balance=sim_balance)

    def connect(self) -> None:
        """Initialize the CLOB client with credentials."""
        if self.simulate:
            # Simulation mode: create a read-only CLOB client (no signing needed)
            # We only use it for fetching order books, not placing real orders
            self._clob = ClobClient(
                self.config.clob_api_url,
                chain_id=self.config.chain_id,
            )
            logger.info("Connected to Polymarket CLOB API (read-only, simulation mode)")
        else:
            self.config.validate()
            self._clob = ClobClient(
                self.config.clob_api_url,
                key=self.config.private_key,
                chain_id=self.config.chain_id,
                creds={
                    "apiKey": self.config.api_key,
                    "secret": self.config.api_secret,
                    "passphrase": self.config.api_passphrase,
                },
            )
            logger.info("Connected to Polymarket CLOB API")

    @property
    def clob(self) -> ClobClient:
        if self._clob is None:
            raise RuntimeError("Client not connected. Call connect() first.")
        return self._clob

    # ── Market Discovery ──────────────────────────────────────────

    async def get_active_markets(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Fetch active markets from the Gamma API."""
        resp = await self._http.get(
            f"{self.config.gamma_api_url}/markets",
            params={
                "limit": limit,
                "offset": offset,
                "active": True,
                "closed": False,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def get_market(self, condition_id: str) -> dict[str, Any]:
        """Fetch a single market by condition ID."""
        resp = await self._http.get(
            f"{self.config.gamma_api_url}/markets/{condition_id}"
        )
        resp.raise_for_status()
        return resp.json()

    def parse_market(self, raw: dict[str, Any]) -> Market:
        """Parse a raw Gamma API market into our Market model."""
        tokens = raw.get("tokens", [])
        yes_token = None
        no_token = None

        for t in tokens:
            outcome = t.get("outcome", "").upper()
            token = Token(
                token_id=t.get("token_id", ""),
                side=Side.YES if outcome == "YES" else Side.NO,
                price=float(t.get("price", 0)),
            )
            if outcome == "YES":
                yes_token = token
            elif outcome == "NO":
                no_token = token

        return Market(
            condition_id=raw.get("condition_id", ""),
            question=raw.get("question", ""),
            slug=raw.get("slug", ""),
            yes_token=yes_token,
            no_token=no_token,
            active=raw.get("active", True),
            volume_24h=float(raw.get("volume_num_24hr", 0) or 0),
            liquidity=float(raw.get("liquidity_num", 0) or 0),
        )

    # ── Order Book ────────────────────────────────────────────────

    def get_order_book(self, token_id: str) -> dict[str, Any]:
        """Fetch the order book for a token.

        In simulation mode, still fetches REAL order book data from
        the CLOB API so prices reflect actual market conditions.
        """
        return self.clob.get_order_book(token_id)

    def parse_order_book(self, raw: dict[str, Any], token_id: str, side: Side) -> OrderBook:
        """Parse raw order book data into our OrderBook model."""
        bids = [
            OrderBookLevel(price=float(b.get("price", 0)), size=float(b.get("size", 0)))
            for b in raw.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=float(a.get("price", 0)), size=float(a.get("size", 0)))
            for a in raw.get("asks", [])
        ]
        # Sort: bids descending, asks ascending
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        return OrderBook(token_id=token_id, side=side, bids=bids, asks=asks)

    # ── Order Placement ───────────────────────────────────────────

    def place_order(
        self,
        token_id: str,
        action: OrderAction,
        price: float,
        size: float,
    ) -> dict[str, Any]:
        """Place a limit order. Routes to simulator or real CLOB."""
        if self.simulate and self.sim_exchange:
            return self.sim_exchange.place_order(token_id, action, price, size)

        clob_side = BUY if action == OrderAction.BUY else SELL
        order_args = OrderArgs(
            price=price,
            size=size,
            side=clob_side,
            token_id=token_id,
        )
        signed_order = self.clob.create_order(order_args)
        result = self.clob.post_order(signed_order, OrderType.GTC)
        logger.info(f"Order placed: {action.value} {size}@{price} token={token_id[:8]}... result={result}")
        return result

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order."""
        if self.simulate and self.sim_exchange:
            return self.sim_exchange.cancel_order(order_id)
        result = self.clob.cancel(order_id)
        logger.info(f"Order cancelled: {order_id}")
        return result

    def cancel_all_orders(self) -> dict[str, Any]:
        """Cancel all open orders."""
        if self.simulate and self.sim_exchange:
            return self.sim_exchange.cancel_all()
        result = self.clob.cancel_all()
        logger.info("All orders cancelled")
        return result

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Get all open orders for this account."""
        if self.simulate and self.sim_exchange:
            return self.sim_exchange.get_orders()
        return self.clob.get_orders()

    def parse_order(self, raw: dict[str, Any]) -> Order:
        """Parse a raw order response into our Order model."""
        status_map = {
            "LIVE": OrderStatus.OPEN,
            "FILLED": OrderStatus.FILLED,
            "CANCELLED": OrderStatus.CANCELLED,
        }
        return Order(
            order_id=raw.get("id", ""),
            token_id=raw.get("asset_id", ""),
            action=OrderAction.BUY if raw.get("side") == "BUY" else OrderAction.SELL,
            price=float(raw.get("price", 0)),
            size=float(raw.get("original_size", 0)),
            filled_size=float(raw.get("size_matched", 0)),
            status=status_map.get(raw.get("status", ""), OrderStatus.PENDING),
        )

    # ── Account ───────────────────────────────────────────────────

    async def get_balance(self) -> float:
        """Get USDC balance (approximate, via API)."""
        try:
            # Polymarket uses conditional tokens on Polygon
            # Balance is tracked through the exchange contract
            return 0.0  # Will be populated by portfolio agent
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0

    async def close(self) -> None:
        """Clean up HTTP client."""
        await self._http.aclose()
