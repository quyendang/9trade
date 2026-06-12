from __future__ import annotations

import math
from typing import Literal

from app.tradebot.models.schema import OrderBookWall


def build_order_book_walls(
    order_book: dict,
    current_price: float,
    bucket_pct: float,
    min_quote: float,
    max_levels: int,
) -> list[OrderBookWall]:
    if current_price <= 0:
        raise ValueError('Cannot build order book walls without a valid current price')
    if bucket_pct <= 0:
        raise ValueError('Order book wall bucket pct must be positive')

    bucket_size = current_price * bucket_pct
    walls: list[OrderBookWall] = []
    walls.extend(
        _build_side_walls(
            side='buy',
            levels=order_book.get('bids', []),
            bucket_size=bucket_size,
            min_quote=min_quote,
        )
    )
    walls.extend(
        _build_side_walls(
            side='sell',
            levels=order_book.get('asks', []),
            bucket_size=bucket_size,
            min_quote=min_quote,
        )
    )

    selected = sorted(walls, key=lambda wall: wall.quote_size, reverse=True)[:max_levels]
    return sorted(selected, key=lambda wall: wall.price)


def _build_side_walls(
    side: Literal['buy', 'sell'],
    levels: list,
    bucket_size: float,
    min_quote: float,
) -> list[OrderBookWall]:
    buckets: dict[int, dict[str, float | int]] = {}
    for raw in levels:
        if len(raw) < 2:
            continue
        try:
            price = float(raw[0])
            quantity = float(raw[1])
        except (TypeError, ValueError):
            continue
        if price <= 0 or quantity <= 0:
            continue

        bucket = math.floor(price / bucket_size)
        low = bucket * bucket_size
        high = low + bucket_size
        quote_size = price * quantity
        existing = buckets.setdefault(
            bucket,
            {
                'low': low,
                'high': high,
                'quantity': 0.0,
                'quote_size': 0.0,
                'level_count': 0,
            },
        )
        existing['quantity'] = float(existing['quantity']) + quantity
        existing['quote_size'] = float(existing['quote_size']) + quote_size
        existing['level_count'] = int(existing['level_count']) + 1

    walls: list[OrderBookWall] = []
    for bucket in buckets.values():
        quote_size = float(bucket['quote_size'])
        if quote_size < min_quote:
            continue
        quantity = float(bucket['quantity'])
        price = quote_size / quantity if quantity else (float(bucket['low']) + float(bucket['high'])) / 2
        walls.append(
            OrderBookWall(
                side=side,
                price=float(price),
                low=float(bucket['low']),
                high=float(bucket['high']),
                quantity=quantity,
                quote_size=quote_size,
                level_count=int(bucket['level_count']),
            )
        )
    return walls
