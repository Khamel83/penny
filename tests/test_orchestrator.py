"""Tests for the background orchestrator components."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestDetermineProbes:
    """Test probe selection logic."""

    def test_selects_atlas_for_query(self):
        """Should select atlas probe when query is present."""
        from penny.orchestrator.probes import determine_probes

        result = determine_probes({"query": "how do I do X?"})
        assert "atlas" in result

    def test_selects_atlas_for_text(self):
        """Should select atlas probe when text is present."""
        from penny.orchestrator.probes import determine_probes

        result = determine_probes({"text": "some text"})
        assert "atlas" in result

    def test_selects_grep_for_search_pattern(self):
        """Should select grep probe for search patterns."""
        from penny.orchestrator.probes import determine_probes

        result = determine_probes({"search_pattern": "TODO:"})
        assert "grep" in result

    def test_selects_file_read_for_file_paths(self):
        """Should select file_read probe for file paths."""
        from penny.orchestrator.probes import determine_probes

        result = determine_probes({"file_paths": ["/etc/hosts"]})
        assert "file_read" in result

    def test_selects_api_check_for_urls(self):
        """Should select api_check probe for URLs."""
        from penny.orchestrator.probes import determine_probes

        result = determine_probes({"check_urls": ["http://localhost:8000/health"]})
        assert "api_check" in result

    def test_selects_command_for_diagnostic(self):
        """Should select command probe for diagnostics."""
        from penny.orchestrator.probes import determine_probes

        result = determine_probes({"command": "ls -la"})
        assert "command" in result

    def test_returns_empty_for_no_data(self):
        """Should return empty list when no relevant data."""
        from penny.orchestrator.probes import determine_probes

        result = determine_probes({})
        assert result == []


class TestCalculateConfidence:
    """Test confidence calculation from findings."""

    def test_returns_zero_for_empty(self):
        """Should return 0 for empty findings."""
        from penny.orchestrator.probes import calculate_confidence

        assert calculate_confidence([]) == 0.0

    def test_weights_successful_probes_higher(self):
        """Successful probes should have higher weight than errors."""
        from penny.orchestrator.probes import calculate_confidence

        # Mixed results
        findings = [
            {"probe": "atlas", "confidence": 0.8},  # success
            {"probe": "grep", "confidence": 0.0, "error": "not found"},  # error
        ]

        result = calculate_confidence(findings)
        # Successful probe weighted 1.0, error weighted 0.5
        # (0.8 * 1.0 + 0.0 * 0.5) / (1.0 + 0.5) = 0.8 / 1.5 = 0.533
        assert 0.5 < result < 0.6

    def test_all_errors_gives_zero(self):
        """All errors should give zero confidence."""
        from penny.orchestrator.probes import calculate_confidence

        findings = [
            {"probe": "atlas", "confidence": 0.0, "error": "not available"},
            {"probe": "grep", "confidence": 0.0, "error": "timeout"},
        ]

        result = calculate_confidence(findings)
        assert result == 0.0

    def test_high_confidence_findings(self):
        """High confidence findings should aggregate well."""
        from penny.orchestrator.probes import calculate_confidence

        findings = [
            {"probe": "atlas", "confidence": 0.9},
            {"probe": "grep", "confidence": 0.85},
        ]

        result = calculate_confidence(findings)
        assert result > 0.8


class TestProbeCommand:
    """Test command probe safety."""

    @pytest.mark.asyncio
    async def test_rejects_unsafe_commands(self):
        """Should reject commands not in safe whitelist."""
        from penny.orchestrator.probes import probe_command

        result = await probe_command({"command": "rm -rf /"})
        assert result["error"] == "Command not in safe whitelist"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_allows_safe_commands(self):
        """Should allow safe commands."""
        from penny.orchestrator.probes import probe_command

        result = await probe_command({"command": "ls -la"})
        assert "error" not in result or result.get("error") is None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_allows_git_status(self):
        """Should allow git status."""
        from penny.orchestrator.probes import probe_command

        result = await probe_command({"command": "git status"})
        # May fail if not in git repo, but shouldn't be blocked
        assert result.get("error") != "Command not in safe whitelist"


class TestProbeGrep:
    """Test grep probe."""

    @pytest.mark.asyncio
    async def test_returns_none_without_pattern(self):
        """Should return None without a pattern."""
        from penny.orchestrator.probes import probe_grep

        result = await probe_grep({})
        assert result is None

    @pytest.mark.asyncio
    async def test_searches_for_pattern(self):
        """Should search for patterns."""
        from penny.orchestrator.probes import probe_grep

        # Search in current directory for something that should exist
        result = await probe_grep({
            "search_pattern": "import",
            "search_path": ".",
        })

        assert result is not None
        assert result["probe"] == "grep"
        assert "total_matches" in result


class TestProbeFileRead:
    """Test file read probe."""

    @pytest.mark.asyncio
    async def test_returns_none_without_paths(self):
        """Should return None without file paths."""
        from penny.orchestrator.probes import probe_file_read

        result = await probe_file_read({})
        assert result is None

    @pytest.mark.asyncio
    async def test_reads_existing_file(self):
        """Should read existing files."""
        from penny.orchestrator.probes import probe_file_read

        result = await probe_file_read({"file_paths": ["pyproject.toml"]})

        assert result is not None
        assert result["files_found"] >= 1
        assert result["confidence"] > 0

    @pytest.mark.asyncio
    async def test_handles_missing_file(self):
        """Should handle missing files gracefully."""
        from penny.orchestrator.probes import probe_file_read

        result = await probe_file_read({"file_paths": ["/nonexistent/file.txt"]})

        assert result is not None
        assert result["files_found"] == 0
        assert result["confidence"] == 0


class TestBackgroundOrchestrator:
    """Test the orchestrator class."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self):
        """Start should set running flag."""
        from penny.orchestrator import BackgroundOrchestrator

        orchestrator = BackgroundOrchestrator(poll_interval=1)

        # Mock the database calls
        with patch("penny.orchestrator.loop.database") as mock_db:
            mock_db.get_pending_background_tasks = AsyncMock(return_value=[])
            mock_db.get_tasks_ready_for_escalation = AsyncMock(return_value=[])

            await orchestrator.start()
            assert orchestrator.running is True

            await orchestrator.stop()
            assert orchestrator.running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """Stop should cancel the background task."""
        from penny.orchestrator import BackgroundOrchestrator

        orchestrator = BackgroundOrchestrator(poll_interval=1)

        with patch("penny.orchestrator.loop.database") as mock_db:
            mock_db.get_pending_background_tasks = AsyncMock(return_value=[])
            mock_db.get_tasks_ready_for_escalation = AsyncMock(return_value=[])

            await orchestrator.start()
            assert orchestrator._task is not None

            await orchestrator.stop()
            assert orchestrator._task is None


class TestRunProbes:
    """Test the run_probes function."""

    @pytest.mark.asyncio
    async def test_runs_multiple_probes(self):
        """Should run multiple applicable probes."""
        from penny.orchestrator.probes import run_probes

        input_data = {
            "query": "test query",
            "search_pattern": "TODO",
        }

        with patch("penny.orchestrator.probes.probe_atlas") as mock_atlas:
            mock_atlas.return_value = {
                "probe": "atlas",
                "confidence": 0.0,
                "error": "Atlas not available",
            }

            results = await run_probes(input_data)

            # Should have results from atlas and grep
            assert len(results) >= 1
            probe_types = [r["probe"] for r in results]
            assert "atlas" in probe_types or "grep" in probe_types

    @pytest.mark.asyncio
    async def test_handles_probe_exceptions(self):
        """Should handle probe exceptions gracefully."""
        from penny.orchestrator.probes import run_probes

        with patch("penny.orchestrator.probes.probe_atlas") as mock_atlas:
            mock_atlas.side_effect = Exception("Probe failed")

            results = await run_probes({"query": "test"})

            # Should have error result
            assert len(results) == 1
            assert results[0]["error"] == "Probe failed"
            assert results[0]["confidence"] == 0.0
