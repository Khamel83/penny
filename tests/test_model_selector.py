"""Tests for model_selector.py."""

import os
import pytest
from unittest.mock import patch


class TestSelectModel:
    """Tests for select_model function."""

    def test_uses_glm_for_normal_requests(self):
        """Normal requests should use GLM via Z.AI."""
        with patch("penny.model_selector.ANTHROPIC_API_KEY", ""):
            from penny.model_selector import select_model

            model, env = select_model("build me a simple website", 0.9)

            assert model == "glm-4.7"
            assert "ANTHROPIC_BASE_URL" in env
            assert env["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"

    def test_uses_opus_for_critical_keyword(self):
        """Requests with 'critical' should use Opus when API key is set."""
        with patch("penny.model_selector.ANTHROPIC_API_KEY", "test-key"):
            from penny.model_selector import select_model

            model, env = select_model("critical: fix the production bug", 0.9)

            assert model == "claude-opus-4"
            assert env.get("ANTHROPIC_API_KEY") == "test-key"

    def test_uses_opus_for_urgent_keyword(self):
        """Requests with 'urgent' should use Opus when API key is set."""
        with patch("penny.model_selector.ANTHROPIC_API_KEY", "test-key"):
            from penny.model_selector import select_model

            model, env = select_model("urgent security patch needed", 0.9)

            assert model == "claude-opus-4"

    def test_uses_opus_for_production_keyword(self):
        """Requests with 'production' should use Opus when API key is set."""
        with patch("penny.model_selector.ANTHROPIC_API_KEY", "test-key"):
            from penny.model_selector import select_model

            model, env = select_model("deploy to production immediately", 0.9)

            assert model == "claude-opus-4"

    def test_uses_opus_for_low_confidence(self):
        """Low confidence should trigger Opus when API key is set."""
        with patch("penny.model_selector.ANTHROPIC_API_KEY", "test-key"):
            from penny.model_selector import select_model

            model, env = select_model("do that thing we discussed", 0.5)

            assert model == "claude-opus-4"

    def test_uses_opus_for_complexity_markers(self):
        """Complexity markers like 'authentication' should trigger Opus."""
        with patch("penny.model_selector.ANTHROPIC_API_KEY", "test-key"):
            from penny.model_selector import select_model

            model, env = select_model("add oauth authentication to the app", 0.9)

            assert model == "claude-opus-4"

    def test_falls_back_to_glm_without_anthropic_key(self):
        """Without ANTHROPIC_API_KEY, should fall back to GLM."""
        with patch("penny.model_selector.ANTHROPIC_API_KEY", ""):
            from penny.model_selector import select_model

            model, env = select_model("critical production emergency", 0.5)

            # Should still be GLM because no Anthropic key
            assert model == "glm-4.7"


class TestGetModelReason:
    """Tests for get_model_reason function."""

    def test_explains_urgency_keyword(self):
        """Should explain when urgency keywords are detected."""
        from penny.model_selector import get_model_reason

        reason = get_model_reason("critical bug fix needed", 0.9)

        assert "critical" in reason.lower()

    def test_explains_low_confidence(self):
        """Should explain when confidence is low."""
        from penny.model_selector import get_model_reason

        reason = get_model_reason("simple website", 0.5)

        assert "confidence" in reason.lower() or "50%" in reason

    def test_explains_normal_build(self):
        """Should explain when using GLM for normal builds."""
        from penny.model_selector import get_model_reason

        reason = get_model_reason("build me a todo app", 0.9)

        assert "GLM" in reason or "standard" in reason.lower()
