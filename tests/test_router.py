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
    request_confirmation,
    CONFIDENCE_THRESHOLD,
)


@pytest.mark.asyncio
class TestRouteDispatcher:
    """Tests for the main route() dispatcher."""

    async def test_routes_shopping(self):
        with patch("penny.router.route_shopping", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "google_keep"}
            result = await route("shopping", "buy milk", {"items": ["milk"]}, confidence=0.9)
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_routes_media(self):
        with patch("penny.router.route_media", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "jellyseerr"}
            result = await route("media", "request Dune", {"title": "Dune"}, confidence=0.9)
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_routes_work(self):
        with patch("penny.router.route_work", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "telegram"}
            result = await route("work", "call dentist", {"task": "call dentist"}, confidence=0.9)
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_routes_smart_home(self):
        with patch("penny.router.route_smart_home", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "home_assistant"}
            result = await route("smart_home", "turn off lights", {"action": "turn_off"}, confidence=0.9)
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_personal_not_routed(self):
        result = await route("personal", "great idea", {}, confidence=0.9)
        assert result["routed"] is False
        assert "Stored in Penny" in result["reason"]

    async def test_unknown_not_routed(self):
        result = await route("unknown", "xyz", {}, confidence=0.9)
        assert result["routed"] is False

    async def test_handles_exception(self):
        with patch("penny.router.route_shopping", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("test error")
            result = await route("shopping", "buy milk", {}, confidence=0.9)
            assert result["routed"] is False
            assert "error" in result


@pytest.mark.asyncio
class TestConfidenceThreshold:
    """Tests for low-confidence confirmation flow."""

    async def test_low_confidence_requests_confirmation(self):
        """Low confidence should trigger confirmation request."""
        with patch("penny.router.request_confirmation", new_callable=AsyncMock) as mock:
            mock.return_value = {"needs_confirmation": True, "routed": False}
            result = await route("shopping", "buy milk", {"items": ["milk"]}, item_id="123", confidence=0.5)
            mock.assert_called_once()
            assert result["needs_confirmation"] is True

    async def test_high_confidence_routes_directly(self):
        """High confidence should route directly without confirmation."""
        with patch("penny.router.route_shopping", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "google_keep"}
            result = await route("shopping", "buy milk", {"items": ["milk"]}, confidence=0.9)
            mock.assert_called_once()
            assert result["routed"] is True

    async def test_personal_skips_confirmation(self):
        """Personal items should never need confirmation."""
        result = await route("personal", "great idea", {}, confidence=0.3)
        assert result["routed"] is False
        assert "needs_confirmation" not in result
        assert "Stored in Penny" in result["reason"]

    async def test_unknown_skips_confirmation(self):
        """Unknown items should never need confirmation."""
        result = await route("unknown", "xyz", {}, confidence=0.3)
        assert result["routed"] is False
        assert "needs_confirmation" not in result


@pytest.mark.asyncio
class TestRequestConfirmation:
    """Tests for the confirmation request function."""

    async def test_sends_telegram_message(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "telegram"}
            result = await request_confirmation("item-123", "shopping", "buy milk", 0.5)
            mock.assert_called_once()
            message = mock.call_args[0][0]
            assert "50%" in message
            assert "shopping" in message
            assert "item-123" in message

    async def test_returns_needs_confirmation(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "telegram"}
            result = await request_confirmation("item-123", "shopping", "buy milk", 0.5)
            assert result["needs_confirmation"] is True
            assert result["routed"] is False

    async def test_truncates_long_text(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock:
            mock.return_value = {"routed": True, "service": "telegram"}
            long_text = "A" * 200
            await request_confirmation("item-123", "shopping", long_text, 0.5)
            message = mock.call_args[0][0]
            assert "..." in message
            assert len(long_text) > 100  # Original was long


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
    """Tests for work route - routes to TrojanHorse with Telegram notification."""

    async def test_routes_to_trojanhorse(self):
        mock_th = AsyncMock(return_value={"success": True, "file": "/inbox/test.md"})
        with patch("penny.integrations.trojanhorse.add_work_note", mock_th):
            with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
                mock_tg.return_value = {"routed": True, "service": "telegram"}
                result = await route_work("call dentist", {"task": "Call the dentist"})
                mock_th.assert_called_once()
                assert result["service"] == "trojanhorse"

    async def test_falls_back_to_telegram_on_import_error(self):
        with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = {"routed": True, "service": "telegram"}
            # TrojanHorse not installed - falls back to Telegram
            result = await route_work("call dentist", {"task": "Call the dentist"})
            mock_tg.assert_called()
            assert "Call the dentist" in mock_tg.call_args[0][0]

    async def test_notifies_telegram_on_success(self):
        mock_th = AsyncMock(return_value={"success": True, "file": "/inbox/test.md"})
        with patch("penny.integrations.trojanhorse.add_work_note", mock_th):
            with patch("penny.router.send_telegram", new_callable=AsyncMock) as mock_tg:
                mock_tg.return_value = {"routed": True, "service": "telegram"}
                await route_work("call dentist", {"task": "Call the dentist"})
                # Should notify via Telegram after saving
                mock_tg.assert_called_once()
                assert "TrojanHorse" in mock_tg.call_args[0][0]


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
