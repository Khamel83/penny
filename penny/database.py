"""SQLite database for Penny."""

import json
import os
import aiosqlite
from pathlib import Path
from typing import Optional
from datetime import datetime

from .models import Item

DATABASE_PATH = Path(os.environ.get("PENNY_DB_PATH", "/app/data/penny.db"))


async def init_db():
    """Initialize the database schema."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                classification TEXT NOT NULL DEFAULT 'unknown',
                confidence REAL NOT NULL DEFAULT 0.0,
                source_file TEXT,
                created_at TEXT NOT NULL,
                routed_to TEXT,
                status TEXT NOT NULL DEFAULT 'processed',
                routing_data TEXT
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_created_at
            ON items(created_at DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_classification
            ON items(classification)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_status
            ON items(status)
        """)
        # Add new columns to existing tables (no-op if they already exist)
        try:
            await db.execute("ALTER TABLE items ADD COLUMN status TEXT NOT NULL DEFAULT 'processed'")
        except Exception:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE items ADD COLUMN routing_data TEXT")
        except Exception:
            pass  # Column already exists
        await db.commit()


async def save_item(item: Item) -> Item:
    """Save an item to the database."""
    routing_data_json = json.dumps(item.routing_data) if item.routing_data else None
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO items (id, text, classification, confidence, source_file, created_at, routed_to, status, routing_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.text,
                item.classification,
                item.confidence,
                item.source_file,
                item.created_at.isoformat(),
                item.routed_to,
                item.status,
                routing_data_json,
            ),
        )
        await db.commit()
    return item


def _row_to_item(row) -> Item:
    """Convert a database row to an Item."""
    routing_data = None
    if row["routing_data"]:
        try:
            routing_data = json.loads(row["routing_data"])
        except json.JSONDecodeError:
            pass
    return Item(
        id=row["id"],
        text=row["text"],
        classification=row["classification"],
        confidence=row["confidence"],
        source_file=row["source_file"],
        created_at=datetime.fromisoformat(row["created_at"]),
        routed_to=row["routed_to"],
        status=row["status"] if "status" in row.keys() else "processed",
        routing_data=routing_data,
    )


async def get_item(item_id: str) -> Optional[Item]:
    """Get an item by ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return _row_to_item(row)
    return None


async def get_items(
    page: int = 1,
    per_page: int = 50,
    classification: Optional[str] = None,
) -> tuple[list[Item], int]:
    """Get paginated items."""
    offset = (page - 1) * per_page

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Build query
        where_clause = ""
        params = []
        if classification:
            where_clause = "WHERE classification = ?"
            params.append(classification)

        # Get total count
        async with db.execute(
            f"SELECT COUNT(*) as count FROM items {where_clause}", params
        ) as cursor:
            row = await cursor.fetchone()
            total = row["count"]

        # Get items
        async with db.execute(
            f"""
            SELECT * FROM items {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ) as cursor:
            rows = await cursor.fetchall()
            items = [_row_to_item(row) for row in rows]

    return items, total


async def update_classification(item_id: str, classification: str) -> Optional[Item]:
    """Update an item's classification."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE items SET classification = ?, confidence = 1.0 WHERE id = ?",
            (classification, item_id),
        )
        await db.commit()

    return await get_item(item_id)


async def update_routed_to(item_id: str, routed_to: str, status: str = "processed") -> Optional[Item]:
    """Update an item's routing destination and status."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE items SET routed_to = ?, status = ? WHERE id = ?",
            (routed_to, status, item_id),
        )
        await db.commit()

    return await get_item(item_id)


async def update_status(item_id: str, status: str) -> Optional[Item]:
    """Update an item's status."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE items SET status = ? WHERE id = ?",
            (status, item_id),
        )
        await db.commit()

    return await get_item(item_id)


async def get_pending_items() -> list[Item]:
    """Get all items pending confirmation."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM items WHERE status = 'pending_confirmation' ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_item(row) for row in rows]
