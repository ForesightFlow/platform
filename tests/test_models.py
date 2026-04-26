"""SQLAlchemy model and schema tests."""

import pytest
from sqlalchemy import inspect

from fflow.models import Base, DataCollectionRun, Market, Price, Trade, Wallet


class TestTableDefinitions:
    def test_all_tables_defined(self):
        table_names = {t for t in Base.metadata.tables}
        assert "markets" in table_names
        assert "prices" in table_names
        assert "trades" in table_names
        assert "wallets" in table_names
        assert "data_collection_runs" in table_names

    def test_markets_primary_key(self):
        pk_cols = [c.name for c in Market.__table__.primary_key]
        assert pk_cols == ["id"]

    def test_prices_composite_pk(self):
        pk_cols = {c.name for c in Price.__table__.primary_key}
        assert pk_cols == {"market_id", "ts"}

    def test_trades_unique_constraint(self):
        constraint_names = {c.name for c in Trade.__table__.constraints}
        assert "uq_trades_tx_log" in constraint_names

    def test_wallets_primary_key(self):
        pk_cols = [c.name for c in Wallet.__table__.primary_key]
        assert pk_cols == ["address"]

    def test_markets_has_category_fflow(self):
        col_names = {c.name for c in Market.__table__.columns}
        assert "category_fflow" in col_names
        assert "category_raw" in col_names

    def test_numeric_columns_not_float(self):
        from sqlalchemy import Numeric
        price_cols = {c.name: c for c in Price.__table__.columns}
        mid_price_type = price_cols["mid_price"].type
        assert isinstance(mid_price_type, Numeric)

    def test_timestamps_have_timezone(self):
        from sqlalchemy import DateTime
        market_cols = {c.name: c for c in Market.__table__.columns}
        resolved_type = market_cols["resolved_at"].type
        assert isinstance(resolved_type, DateTime)
        assert resolved_type.timezone is True
