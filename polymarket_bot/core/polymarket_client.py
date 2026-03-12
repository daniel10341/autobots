"""Polymarket CLOB API client wrapper."""

import logging
import time
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


class TTLCache:
    """Simple in-memory cache with per-key TTL."""

    def __init__(self, default_ttl: float = 2.0) -> None:
        self._store: dict[str, tuple[float, Any]] = {}  # key -> (expires_at, value)
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self._store[key] = (time.monotonic() + (ttl or self.default_ttl), value)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]

    @property
    def size(self) -> int:
        return len(self._store)


class PolymarketClient:
    """Unified client for Polymarket CLOB and Gamma APIs.

    Wraps py-clob-client and provides methods used by all agents.
    In simulation mode, uses real market data but simulated execution.
    """

    def __init__(self, config: PolymarketConfig, simulate: bool = False, sim_balance: float = 1000.0, capital_max: float = 0.0) -> None:
        self.config = config
        self._clob: Optional[ClobClient] = None
        self._http = httpx.AsyncClient(timeout=30.0)
        self.simulate = simulate
        self.sim_exchange: Optional[SimulatedExchange] = None
        if simulate:
            self.sim_exchange = SimulatedExchange(starting_balance=sim_balance, capital_max=capital_max)

        # Caches — order books change fast (2s TTL), markets are slower (30s TTL)
        self._orderbook_cache = TTLCache(default_ttl=2.0)
        self._market_cache = TTLCache(default_ttl=30.0)
        self._event_cache = TTLCache(default_ttl=30.0)

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
        """Fetch active markets from the Gamma API (cached 30s)."""
        cache_key = f"markets:{limit}:{offset}"
        cached = self._market_cache.get(cache_key)
        if cached is not None:
            return cached
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
        result = resp.json()
        self._market_cache.set(cache_key, result)
        return result

    async def get_market(self, condition_id: str) -> dict[str, Any]:
        """Fetch a single market by condition ID (cached 30s)."""
        cache_key = f"market:{condition_id}"
        cached = self._market_cache.get(cache_key)
        if cached is not None:
            return cached
        resp = await self._http.get(
            f"{self.config.gamma_api_url}/markets/{condition_id}"
        )
        resp.raise_for_status()
        result = resp.json()
        self._market_cache.set(cache_key, result)
        return result

    async def get_event(self, slug: str) -> list[dict[str, Any]]:
        """Fetch events by slug from the Gamma API (cached 30s)."""
        cache_key = f"event:{slug}"
        cached = self._event_cache.get(cache_key)
        if cached is not None:
            return cached
        resp = await self._http.get(
            f"{self.config.gamma_api_url}/events",
            params={"slug": slug},
        )
        resp.raise_for_status()
        result = resp.json()
        self._event_cache.set(cache_key, result)
        return result

    def parse_market(self, raw: dict[str, Any]) -> Market:
        """Parse a raw Gamma API market into our Market model."""
        yes_token = None
        no_token = None

        # Gamma API uses clobTokenIds [yes_id, no_id] and outcomePrices
        clob_ids = raw.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            import json as _json
            try:
                clob_ids = _json.loads(clob_ids)
            except Exception:
                clob_ids = []

        outcome_prices = raw.get("outcomePrices", [])
        if isinstance(outcome_prices, str):
            import json as _json
            try:
                outcome_prices = _json.loads(outcome_prices)
            except Exception:
                outcome_prices = []

        if len(clob_ids) >= 2:
            yes_price = float(outcome_prices[0]) if len(outcome_prices) >= 1 else 0
            no_price = float(outcome_prices[1]) if len(outcome_prices) >= 2 else 0
            yes_token = Token(token_id=clob_ids[0], side=Side.YES, price=yes_price)
            no_token = Token(token_id=clob_ids[1], side=Side.NO, price=no_price)

        # Also try legacy "tokens" array format
        if not yes_token:
            for t in raw.get("tokens", []):
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
            condition_id=raw.get("conditionId", raw.get("condition_id", "")),
            question=raw.get("question", ""),
            slug=raw.get("slug", ""),
            yes_token=yes_token,
            no_token=no_token,
            active=raw.get("active", True),
            volume_24h=float(raw.get("volumeNum", raw.get("volume_num_24hr", 0)) or 0),
            liquidity=float(raw.get("liquidityNum", raw.get("liquidity_num", 0)) or 0),
        )

    # ── Order Book ────────────────────────────────────────────────

    def get_order_book(self, token_id: str) -> Any:
        """Fetch the order book for a token (cached 2s).

        In simulation mode, still fetches REAL order book data from
        the CLOB API so prices reflect actual market conditions.
        Returns an OrderBookSummary object or dict.
        """
        cache_key = f"book:{token_id}"
        cached = self._orderbook_cache.get(cache_key)
        if cached is not None:
            return cached
        result = self.clob.get_order_book(token_id)
        self._orderbook_cache.set(cache_key, result)
        return result

    def parse_order_book(self, raw: Any, token_id: str, side: Side) -> OrderBook:
        """Parse raw order book data into our OrderBook model.

        Handles both dict format and py-clob-client OrderBookSummary objects.
        """
        # Get bids/asks — handle both dict and object attribute access
        if isinstance(raw, dict):
            raw_bids = raw.get("bids", [])
            raw_asks = raw.get("asks", [])
        else:
            raw_bids = getattr(raw, "bids", []) or []
            raw_asks = getattr(raw, "asks", []) or []

        def parse_level(entry: Any) -> OrderBookLevel:
            if isinstance(entry, dict):
                return OrderBookLevel(price=float(entry.get("price", 0)), size=float(entry.get("size", 0)))
            else:
                return OrderBookLevel(price=float(getattr(entry, "price", 0)), size=float(getattr(entry, "size", 0)))

        bids = [parse_level(b) for b in raw_bids]
        asks = [parse_level(a) for a in raw_asks]

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
        self._market_cache.invalidate("open_orders")
        logger.info(f"Order placed: {action.value} {size}@{price} token={token_id[:8]}... result={result}")
        return result

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order."""
        if self.simulate and self.sim_exchange:
            return self.sim_exchange.cancel_order(order_id)
        result = self.clob.cancel(order_id)
        self._market_cache.invalidate("open_orders")
        logger.info(f"Order cancelled: {order_id}")
        return result

    def cancel_all_orders(self) -> dict[str, Any]:
        """Cancel all open orders."""
        if self.simulate and self.sim_exchange:
            return self.sim_exchange.cancel_all()
        result = self.clob.cancel_all()
        self._market_cache.invalidate("open_orders")
        logger.info("All orders cancelled")
        return result

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Get all open orders for this account (cached 5s)."""
        if self.simulate and self.sim_exchange:
            return self.sim_exchange.get_orders()
        cached = self._market_cache.get("open_orders")
        if cached is not None:
            return cached
        result = self.clob.get_orders()
        self._market_cache.set("open_orders", result, ttl=5.0)
        return result

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
