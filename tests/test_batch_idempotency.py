"""Tests for subgraph batch idempotency, jsonl checkpoint, and resume."""

import json
import pathlib
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fflow.cli import _load_resume_set, _write_progress


# ---------------------------------------------------------------------------
# _write_progress / _load_resume_set unit tests
# ---------------------------------------------------------------------------

class TestJsonlCheckpoint:
    def test_writes_one_line_per_call(self, tmp_path):
        p = tmp_path / "progress.jsonl"
        _write_progress(p, "0xaaa", "ok", 100, 20, 1500)
        _write_progress(p, "0xbbb", "failed", 0, 0, 300)
        lines = p.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_each_line_is_valid_json(self, tmp_path):
        p = tmp_path / "progress.jsonl"
        _write_progress(p, "0xaaa", "ok", 100, 20, 1500)
        rec = json.loads(p.read_text().strip())
        assert rec["market_id"] == "0xaaa"
        assert rec["status"] == "ok"
        assert rec["trades_count"] == 100
        assert rec["wallets_count"] == 20
        assert rec["duration_ms"] == 1500
        assert "ts" in rec

    def test_append_does_not_overwrite(self, tmp_path):
        p = tmp_path / "progress.jsonl"
        _write_progress(p, "0xaaa", "ok", 10, 2, 100)
        _write_progress(p, "0xbbb", "ok", 20, 4, 200)
        records = [json.loads(l) for l in p.read_text().strip().split("\n")]
        assert records[0]["market_id"] == "0xaaa"
        assert records[1]["market_id"] == "0xbbb"

    def test_schema_fields_present(self, tmp_path):
        p = tmp_path / "progress.jsonl"
        _write_progress(p, "0xccc", "skipped", 0, 0, 50)
        rec = json.loads(p.read_text().strip())
        for field in ("market_id", "status", "trades_count", "wallets_count", "duration_ms", "ts"):
            assert field in rec, f"missing field: {field}"


# ---------------------------------------------------------------------------
# _load_resume_set
# ---------------------------------------------------------------------------

class TestLoadResumeSet:
    def test_returns_empty_set_when_no_file(self, tmp_path):
        result = _load_resume_set(tmp_path / "nonexistent.jsonl")
        assert result == set()

    def test_returns_only_ok_statuses(self, tmp_path):
        p = tmp_path / "progress.jsonl"
        _write_progress(p, "0xaaa", "ok", 100, 10, 500)
        _write_progress(p, "0xbbb", "failed", 0, 0, 100)
        _write_progress(p, "0xccc", "skipped", 0, 0, 200)
        _write_progress(p, "0xddd", "ok", 50, 5, 300)
        result = _load_resume_set(p)
        assert result == {"0xaaa", "0xddd"}
        assert "0xbbb" not in result
        assert "0xccc" not in result

    def test_tolerates_malformed_lines(self, tmp_path):
        p = tmp_path / "progress.jsonl"
        p.write_text('{"market_id": "0xaaa", "status": "ok", "ts": "x"}\nNOT_JSON\n{"market_id": "0xbbb", "status": "ok", "ts": "x"}\n')
        result = _load_resume_set(p)
        assert "0xaaa" in result
        assert "0xbbb" in result

    def test_empty_file_returns_empty_set(self, tmp_path):
        p = tmp_path / "progress.jsonl"
        p.write_text("")
        assert _load_resume_set(p) == set()


# ---------------------------------------------------------------------------
# Integration: batch skips already-collected markets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_skips_already_collected_markets():
    """Market resolved >1 day ago with existing trades must be skipped without calling collector."""
    from fflow.cli import _subgraph_batch

    stale_resolved = datetime.now(UTC) - timedelta(days=2)
    market_id = "0xdeadbeef00000000000000000000000000000000000000000000000000000001"
    mock_rows = [(market_id, "999999.0", stale_resolved)]

    collector_run_called = []

    # Session 1: market list query; Session 2: trade count query
    session1 = AsyncMock()
    session1.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=mock_rows)))
    session2 = AsyncMock()
    session2.scalar = AsyncMock(return_value=42)  # 42 existing trades

    ctx1 = MagicMock()
    ctx1.__aenter__ = AsyncMock(return_value=session1)
    ctx1.__aexit__ = AsyncMock(return_value=False)
    ctx2 = MagicMock()
    ctx2.__aenter__ = AsyncMock(return_value=session2)
    ctx2.__aexit__ = AsyncMock(return_value=False)

    mock_collector = MagicMock()
    mock_collector.run = AsyncMock(side_effect=lambda **kw: collector_run_called.append(kw))

    with (
        patch("fflow.db.AsyncSessionLocal", side_effect=[ctx1, ctx2]),
        patch("fflow.collectors.subgraph.SubgraphCollector", return_value=mock_collector),
        patch("fflow.cli._write_progress"),
        patch("fflow.cli._load_resume_set", return_value=set()),
    ):
        await _subgraph_batch(min_volume=50000, dry_run=False)

    assert len(collector_run_called) == 0, "collector.run() must not be called for already-collected market"


@pytest.mark.asyncio
async def test_batch_writes_jsonl_checkpoint():
    """Each successfully processed market must produce one jsonl line with correct fields."""
    from fflow.cli import _subgraph_batch
    from fflow.collectors.base import CollectorResult

    market_id = "0xfeed000000000000000000000000000000000000000000000000000000000001"
    # Fresh market — resolved only 1 hour ago, idempotency skip won't trigger
    fresh_resolved = datetime.now(UTC) - timedelta(hours=1)
    mock_rows = [(market_id, "100000.0", fresh_resolved)]

    result = CollectorResult(
        collector="subgraph_trades",
        target=market_id,
        n_written=500,
        n_wallets=80,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="success",
    )

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=mock_rows)))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    mock_collector = MagicMock()
    mock_collector.run = AsyncMock(return_value=result)

    written: list[dict] = []

    def capture_write(path, market_id, status, trades_count, wallets_count, duration_ms):
        written.append({
            "market_id": market_id, "status": status,
            "trades_count": trades_count, "wallets_count": wallets_count,
            "duration_ms": duration_ms,
        })

    with (
        patch("fflow.db.AsyncSessionLocal", return_value=ctx),
        patch("fflow.collectors.subgraph.SubgraphCollector", return_value=mock_collector),
        patch("fflow.cli._write_progress", side_effect=capture_write),
        patch("fflow.cli._load_resume_set", return_value=set()),
    ):
        await _subgraph_batch(min_volume=50000, dry_run=False)

    assert len(written) == 1
    assert written[0]["market_id"] == market_id
    assert written[0]["status"] == "ok"
    assert written[0]["trades_count"] == 500
    assert written[0]["wallets_count"] == 80
    assert written[0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_batch_resumes_from_checkpoint():
    """Markets in checkpoint with status=ok must be skipped; new markets must be processed."""
    from fflow.cli import _subgraph_batch
    from fflow.collectors.base import CollectorResult

    done_market = "0xdone0000000000000000000000000000000000000000000000000000000001"
    new_market  = "0xnew00000000000000000000000000000000000000000000000000000000001"
    resolved_at = datetime.now(UTC) - timedelta(hours=1)
    mock_rows = [
        (done_market, "200000.0", resolved_at),
        (new_market,  "100000.0", resolved_at),
    ]

    new_result = CollectorResult(
        collector="subgraph_trades", target=new_market, n_written=300, n_wallets=40,
        started_at=datetime.now(UTC), finished_at=datetime.now(UTC), status="success",
    )

    processed: list[str] = []

    async def fake_run(market_id, **kwargs):
        processed.append(market_id)
        return new_result

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=mock_rows)))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    mock_collector = MagicMock()
    mock_collector.run = AsyncMock(side_effect=fake_run)

    with (
        patch("fflow.db.AsyncSessionLocal", return_value=ctx),
        patch("fflow.collectors.subgraph.SubgraphCollector", return_value=mock_collector),
        patch("fflow.cli._write_progress"),
        patch("fflow.cli._load_resume_set", return_value={done_market}),
    ):
        await _subgraph_batch(min_volume=50000, dry_run=False)

    assert done_market not in processed, "already-done market must be skipped"
    assert new_market in processed, "new market must be processed"
