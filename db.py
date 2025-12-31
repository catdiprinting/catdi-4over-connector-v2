# db.py
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema() -> None:
    """
    Creates baseprice_cache table if missing and performs a tiny migration if payload column is missing.
    Safe to run on every request.
    """
    with engine.begin() as conn:
        # 1) Create table if it doesn't exist (payload included)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id SERIAL PRIMARY KEY,
                    product_uuid VARCHAR NOT NULL,
                    payload JSONB NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        )

        # 2) Migration: add payload column if an older table exists without it
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name='baseprice_cache'
                          AND column_name='payload'
                    ) THEN
                        ALTER TABLE baseprice_cache ADD COLUMN payload JSONB NULL;
                    END IF;
                END$$;
                """
            )
        )

        # Optional: helpful index for lookups
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_baseprice_cache_product_uuid
                ON baseprice_cache (product_uuid);
                """
            )
        )


def insert_baseprice_cache(product_uuid: str, payload: dict) -> int:
    ensure_schema()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO baseprice_cache (product_uuid, payload)
                VALUES (:product_uuid, :payload::jsonb)
                RETURNING id;
                """
            ),
            {"product_uuid": product_uuid, "payload": payload},
        ).fetchone()
        return int(row[0])


def list_baseprice_cache(limit: int = 25) -> list[dict]:
    ensure_schema()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, product_uuid, payload, created_at
                FROM baseprice_cache
                ORDER BY id DESC
                LIMIT :limit;
                """
            ),
            {"limit": limit},
        ).fetchall()

    return [
        {
            "id": r[0],
            "product_uuid": r[1],
            "payload": r[2] if r[2] is not None else None,
            "created_at": r[3].isoformat() if r[3] else None,
        }
        for r in rows
    ]


def latest_baseprice_cache(product_uuid: str) -> dict | None:
    ensure_schema()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, product_uuid, payload, created_at
                FROM baseprice_cache
                WHERE product_uuid = :product_uuid
                ORDER BY id DESC
                LIMIT 1;
                """
            ),
            {"product_uuid": product_uuid},
        ).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "product_uuid": row[1],
        "payload": row[2] if row[2] is not None else None,
        "created_at": row[3].isoformat() if row[3] else None,
    }
