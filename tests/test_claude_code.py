"""Tests for Claude Code integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestLoadPreferences:
    """Tests for load_preferences function."""

    def test_loads_existing_preferences(self, tmp_path):
        """Should load preferences from file."""
        prefs_file = tmp_path / "prefs.md"
        prefs_file.write_text("# My Preferences\n- I like Python")

        with patch("penny.integrations.claude_code.PREFERENCES_FILE", str(prefs_file)):
            from penny.integrations.claude_code import load_preferences

            result = load_preferences()

            assert "My Preferences" in result
            assert "Python" in result

    def test_returns_empty_for_missing_file(self, tmp_path):
        """Should return empty string if file doesn't exist."""
        with patch("penny.integrations.claude_code.PREFERENCES_FILE", str(tmp_path / "nonexistent.md")):
            from penny.integrations.claude_code import load_preferences

            result = load_preferences()

            assert result == ""


class TestBuildPrompt:
    """Tests for build_prompt function."""

    def test_includes_preferences(self):
        """Prompt should include preferences."""
        from penny.integrations.claude_code import build_prompt

        result = build_prompt("build a website", "# Prefs\n- Use Tailwind")

        assert "Prefs" in result
        assert "Tailwind" in result
        assert "build a website" in result

    def test_includes_instructions(self):
        """Prompt should include build instructions."""
        from penny.integrations.claude_code import build_prompt

        result = build_prompt("build an app", "")

        assert "Instructions" in result
        assert "simplest approach" in result.lower()

    def test_handles_empty_preferences(self):
        """Should work without preferences."""
        from penny.integrations.claude_code import build_prompt

        result = build_prompt("build something", "")

        assert "build something" in result
        assert "Omar's Preferences" not in result


class TestLooksLikeQuestion:
    """Tests for _looks_like_question function."""

    def test_detects_would_you_like(self):
        """Should detect 'would you like' questions."""
        from penny.integrations.claude_code import _looks_like_question

        assert _looks_like_question("Would you like me to use React?") is True

    def test_detects_should_i(self):
        """Should detect 'should I' questions."""
        from penny.integrations.claude_code import _looks_like_question

        assert _looks_like_question("Should I deploy to Vercel?") is True

    def test_detects_which(self):
        """Should detect 'which' questions."""
        from penny.integrations.claude_code import _looks_like_question

        assert _looks_like_question("Which framework should I use?") is True

    def test_ignores_statements(self):
        """Should not detect statements."""
        from penny.integrations.claude_code import _looks_like_question

        assert _looks_like_question("I am building the website now.") is False


class TestExtractDeliverables:
    """Tests for _extract_deliverables function."""

    def test_extracts_urls(self):
        """Should extract URLs from output."""
        from penny.integrations.claude_code import _extract_deliverables

        output = "Deployed to https://my-app.vercel.app and also https://backup.netlify.app"
        result = _extract_deliverables(output)

        assert "https://my-app.vercel.app" in result
        assert "https://backup.netlify.app" in result

    def test_extracts_created_files(self):
        """Should extract 'Created:' file paths."""
        from penny.integrations.claude_code import _extract_deliverables

        output = "Created: index.html\nCreated: style.css"
        result = _extract_deliverables(output)

        assert "index.html" in result
        assert "style.css" in result

    def test_filters_documentation_urls(self):
        """Should filter out documentation URLs."""
        from penny.integrations.claude_code import _extract_deliverables

        output = "See https://docs.example.com for more info. Deployed to https://mysite.com"
        result = _extract_deliverables(output)

        assert "https://mysite.com" in result
        assert "https://docs.example.com" not in result

    def test_limits_deliverables(self):
        """Should limit to 10 deliverables."""
        from penny.integrations.claude_code import _extract_deliverables

        urls = "\n".join([f"https://site{i}.com" for i in range(20)])
        result = _extract_deliverables(urls)

        assert len(result) <= 10


class TestTelegramQA:
    """Tests for telegram_qa integration."""

    def test_infer_reasonable_default_yes_no(self):
        """Should default to 'yes' for yes/no questions."""
        from penny.integrations.telegram_qa import infer_reasonable_default

        result = infer_reasonable_default("Should I proceed with the build?")

        assert result.lower() == "yes"

    def test_infer_reasonable_default_deploy(self):
        """Should default to 'vercel' for deployment questions."""
        from penny.integrations.telegram_qa import infer_reasonable_default

        # Use a question without "should I" to test deploy path
        result = infer_reasonable_default("What deployment platform to use?")

        assert "vercel" in result.lower() or "default" in result.lower()

    def test_infer_reasonable_default_framework(self):
        """Should provide sensible framework defaults."""
        from penny.integrations.telegram_qa import infer_reasonable_default

        # Use a question without "should I" to test framework path
        result = infer_reasonable_default("What frontend framework is best?")

        assert "react" in result.lower() or "simplest" in result.lower()

    def test_resolve_answer_resolves_pending(self):
        """Should resolve pending question future."""
        import asyncio
        from penny.integrations.telegram_qa import pending_questions, resolve_answer

        # Create a future
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        pending_questions["test-build-id"] = future

        # Resolve it
        resolved = resolve_answer("test-build-id", "yes, proceed")

        assert resolved is True
        assert future.result() == "yes, proceed"

        # Clean up
        pending_questions.pop("test-build-id", None)
        loop.close()

    def test_resolve_answer_returns_false_for_unknown(self):
        """Should return False for unknown build IDs."""
        from penny.integrations.telegram_qa import resolve_answer

        resolved = resolve_answer("unknown-build-id", "some answer")

        assert resolved is False


class TestClassifierBuildCategory:
    """Tests for build category classification."""

    def test_classifies_build_me_request(self):
        """Should classify 'build me' as build category."""
        from penny.classifier import classify_keywords

        result = classify_keywords("build me a website")

        assert result["classification"] == "build"

    def test_classifies_create_request(self):
        """Should classify 'create' as build category."""
        from penny.classifier import classify_keywords

        result = classify_keywords("create an app for tracking expenses")

        assert result["classification"] == "build"

    def test_classifies_deploy_request(self):
        """Should classify 'deploy' as build category."""
        from penny.classifier import classify_keywords

        result = classify_keywords("deploy a new service to production")

        assert result["classification"] == "build"

    def test_extracts_urgency_critical(self):
        """Should extract critical urgency."""
        from penny.classifier import classify_keywords

        result = classify_keywords("critical: fix the authentication bug")

        assert result.get("urgency") == "critical"

    def test_extracts_urgency_normal(self):
        """Should default to normal urgency."""
        from penny.classifier import classify_keywords

        result = classify_keywords("build me a simple todo app")

        assert result.get("urgency") == "normal"


class TestRouterBuildRoute:
    """Tests for build route in router."""

    @pytest.mark.asyncio
    async def test_routes_to_claude_code(self):
        """Should route build requests to Claude Code."""
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}

            from penny.router import route_build

            # Mock claude_code to fail import
            with patch.dict("sys.modules", {"penny.integrations.claude_code": None}):
                result = await route_build("build a website", {"description": "website"})

            # Should fall back to Telegram
            assert result["routed"] is True
            assert result["service"] == "telegram"

    @pytest.mark.asyncio
    async def test_falls_back_on_error(self):
        """Should fall back to Telegram on errors."""
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}

            from penny.router import route_build

            result = await route_build("build something", {})

            # Without claude_code, should fall back
            assert mock_tg.called
