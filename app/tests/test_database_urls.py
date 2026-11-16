"""Database URLs must name their driver.

SQLAlchemy 2.1 resolves a bare ``postgresql://`` URL to psycopg 3, which this
project does not install. Naming the driver keeps migrations working on every
supported SQLAlchemy release.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url

from app.core.config import DatabaseSettings


def test_sync_url_names_psycopg2() -> None:
    url = make_url(DatabaseSettings().sync_url)
    assert url.drivername == "postgresql+psycopg2"
    assert url.get_dialect().driver == "psycopg2"


def test_async_url_names_asyncpg() -> None:
    url = make_url(DatabaseSettings().async_url)
    assert url.drivername == "postgresql+asyncpg"
