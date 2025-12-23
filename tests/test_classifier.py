"""Tests for the classifier module."""

import json
from unittest.mock import patch, MagicMock

import pytest

from penny.classifier import classify_keywords, classify_with_llm, classify


class TestKeywordClassifier:
    """Tests for keyword-based classification fallback."""

    def test_shopping_keywords(self):
        result = classify_keywords("Add milk and eggs to my shopping list")
        assert result["classification"] == "shopping"
        assert result["confidence"] > 0

    def test_media_keywords(self):
        result = classify_keywords("Download the movie Inception")
        assert result["classification"] == "media"

    def test_work_keywords(self):
        result = classify_keywords("Finish the project report for the client")
        assert result["classification"] == "work"

    def test_smart_home_keywords(self):
        result = classify_keywords("Turn off the lights in the bedroom")
        assert result["classification"] == "smart_home"

    def test_personal_keywords(self):
        result = classify_keywords("Just testing this out")
        assert result["classification"] == "personal"

    def test_reminder_keywords(self):
        result = classify_keywords("Remind me about the appointment tomorrow")
        assert result["classification"] == "reminder"

    def test_calendar_keywords(self):
        result = classify_keywords("Schedule a meeting with the team")
        assert result["classification"] == "calendar"

    def test_notes_keywords(self):
        result = classify_keywords("Write down this great idea for the app")
        assert result["classification"] == "notes"

    def test_unknown_classification(self):
        result = classify_keywords("xyz abc 123")
        assert result["classification"] == "unknown"
        assert result["confidence"] == 0.0

    def test_shopping_extracts_items(self):
        result = classify_keywords("buy apples oranges bananas")
        assert result["classification"] == "shopping"
        assert "items" in result
        assert "apples" in result["items"]

    def test_work_extracts_task(self):
        result = classify_keywords("need to finish the project deadline for client")
        assert result["classification"] == "work"
        assert "task" in result


class TestLLMClassifier:
    """Tests for LLM-based classification."""

    def test_falls_back_without_api_key(self):
        """Without API key, should use keyword classifier."""
        with patch("penny.classifier.OPENROUTER_API_KEY", ""):
            result = classify_with_llm("Add milk to shopping list")
            assert result["classification"] == "shopping"

    @patch("penny.classifier.requests.post")
    def test_parses_llm_response(self, mock_post):
        """Should parse valid JSON from LLM."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"classification": "media", "confidence": 0.95, "title": "Dune", "type": "movie"}'
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch("penny.classifier.OPENROUTER_API_KEY", "test-key"):
            result = classify_with_llm("Request the movie Dune")
            assert result["classification"] == "media"
            assert result["title"] == "Dune"
            assert result["type"] == "movie"

    @patch("penny.classifier.requests.post")
    def test_strips_markdown_code_blocks(self, mock_post):
        """Should handle markdown-wrapped JSON responses."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"classification": "shopping", "confidence": 0.9, "items": ["milk"]}\n```'
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch("penny.classifier.OPENROUTER_API_KEY", "test-key"):
            result = classify_with_llm("Add milk")
            assert result["classification"] == "shopping"
            assert result["items"] == ["milk"]

    @patch("penny.classifier.requests.post")
    def test_falls_back_on_invalid_json(self, mock_post):
        """Should fall back to keywords if LLM returns invalid JSON."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "not valid json"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch("penny.classifier.OPENROUTER_API_KEY", "test-key"):
            result = classify_with_llm("Add milk to my shopping list")
            assert result["classification"] == "shopping"

    @patch("penny.classifier.requests.post")
    def test_falls_back_on_api_error(self, mock_post):
        """Should fall back to keywords on API errors."""
        mock_post.side_effect = Exception("API error")

        with patch("penny.classifier.OPENROUTER_API_KEY", "test-key"):
            result = classify_with_llm("Add milk to my shopping list")
            assert result["classification"] == "shopping"

    @patch("penny.classifier.requests.post")
    def test_validates_classification_category(self, mock_post):
        """Should default to unknown for invalid categories."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"classification": "invalid_category", "confidence": 0.9}'
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch("penny.classifier.OPENROUTER_API_KEY", "test-key"):
            result = classify_with_llm("test")
            assert result["classification"] == "unknown"


class TestClassifyFunction:
    """Tests for the main classify() entry point."""

    def test_classify_uses_llm_when_available(self):
        """classify() should attempt LLM first."""
        with patch("penny.classifier.classify_with_llm") as mock_llm:
            mock_llm.return_value = {"classification": "media", "confidence": 0.9}
            result = classify("test")
            mock_llm.assert_called_once_with("test")
            assert result["classification"] == "media"
