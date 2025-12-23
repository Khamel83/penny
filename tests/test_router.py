"""Tests for the router module."""

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from penny.router import (
    route,
    route_shopping,
    route_media,
    route_work,
    route_smart_home,
    send_telegram,
)


@pytest.mark.asyncio
class TestRouteDispatcher:
    """Tests for the main route() dispatcher."""

    async def test_routes_shopping(self):
        with patch("penny.router.route_shopping", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "google_keep"}
            result = await route("shopping", "buy milk", {"items": ["milk"]})
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_routes_media(self):
        with patch("penny.router.route_media", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "jellyseerr"}
            result = await route("media", "request Dune", {"title": "Dune"})
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_routes_work(self):
        with patch("penny.router.route_work", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "telegram"}
            result = await route("work", "call dentist", {"task": "call dentist"})
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_routes_smart_home(self):
        with patch("penny.router.route_smart_home", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "home_assistant"}
            result = await route("smart_home", "turn off lights", {"action": "turn_off"})
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_personal_not_routed(self):
        result = await route("personal", "great idea", {})
        assert result["routed"] is False
        assert "Stored in Penny" in result["reason"]

    async def test_unknown_not_routed(self):
        result = await route("unknown", "xyz", {})
        assert result["routed"] is False

    async def test_handles_exception(self):
        with patch("penny.router.route_shopping", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("test error")
            result = await route("shopping", "buy milk", {})
            assert result["routed"] is False
            assert "error" in result


@pytest.mark.asyncio
class TestRouteShopping:
    """Tests for shopping route."""

    async def test_falls_back_to_telegram_on_import_error(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}
            # google_keep import will fail since no real module
            result = await route_shopping("buy milk", {"items": ["milk"]})
            assert result["service"] == "telegram"

    async def test_uses_text_when_no_items(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}
            await route_shopping("buy some groceries", {})
            call_args = mock_tg.call_args[0][0]
            assert "buy some groceries" in call_args


@pytest.mark.asyncio
class TestRouteMedia:
    """Tests for media route."""

    async def test_falls_back_to_telegram_on_import_error(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}
            result = await route_media("request Dune", {"title": "Dune", "type": "movie"})
            assert result["service"] == "telegram"


@pytest.mark.asyncio
class TestRouteWork:
    """Tests for work route."""

    async def test_sends_task_to_telegram(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}
            result = await route_work("call dentist", {"task": "Call the dentist"})
            mock_tg.assert_called_once()
            assert "Call the dentist" in mock_tg.call_args[0][0]

    async def test_includes_due_date(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}
            await route_work("call dentist", {"task": "Call dentist", "due": "tomorrow"})
            call_args = mock_tg.call_args[0][0]
            assert "tomorrow" in call_args
            assert "Due:" in call_args


@pytest.mark.asyncio
class TestRouteSmartHome:
    """Tests for smart home route."""

    async def test_falls_back_to_telegram_on_import_error(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}
            result = await route_smart_home("turn off lights", {"action": "turn_off", "entity": "lights"})
            assert result["service"] == "telegram"


@pytest.mark.asyncio
class TestSendTelegram:
    """Tests for Telegram fallback."""

    async def test_returns_error_without_config(self):
        with patch("penny.router.TELEGRAM_BOT_TOKEN", ""):
            result = await send_telegram("test message")
            assert result["routed"] is False
            assert "not configured" in result["error"]

    async def test_sends_via_integration(self):
        with patch("penny.router.TELEGRAM_BOT_TOKEN", "test-token"):
            with patch("penny.router.TELEGRAM_CHAT_ID", "123"):
                with patch("penny.integrations.telegram.send_message", new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = {"ok": True}
                    result = await send_telegram("test message")
                    assert result["routed"] is True
                    assert result["service"] == "telegram"
