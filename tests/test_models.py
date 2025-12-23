"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from penny.models import (
    IngestRequest,
    Item,
    ReclassifyRequest,
    ItemResponse,
    ItemsResponse,
)


class TestIngestRequest:
    """Tests for IngestRequest model."""

    def test_valid_request(self):
        req = IngestRequest(text="test memo")
        assert req.text == "test memo"
        assert req.source_file is None
        assert req.timestamp is None

    def test_with_optional_fields(self):
        req = IngestRequest(
            text="test memo",
            source_file="memo.m4a",
        )
        assert req.source_file == "memo.m4a"

    def test_requires_text(self):
        with pytest.raises(ValidationError):
            IngestRequest()


class TestItem:
    """Tests for Item model."""

    def test_default_values(self):
        item = Item(text="test")
        assert item.text == "test"
        assert item.classification == "unknown"
        assert item.confidence == 0.0
        assert item.id is not None
        assert item.routed_to is None

    def test_generates_unique_ids(self):
        item1 = Item(text="test1")
        item2 = Item(text="test2")
        assert item1.id != item2.id


class TestReclassifyRequest:
    """Tests for ReclassifyRequest validation."""

    def test_valid_classifications(self):
        valid = ["work", "personal", "shopping", "media", "smart_home", "unknown"]
        for classification in valid:
            req = ReclassifyRequest(classification=classification)
            assert req.classification == classification

    def test_rejects_invalid_classification(self):
        with pytest.raises(ValidationError):
            ReclassifyRequest(classification="invalid")

    def test_rejects_empty_classification(self):
        with pytest.raises(ValidationError):
            ReclassifyRequest(classification="")

    def test_case_sensitive(self):
        with pytest.raises(ValidationError):
            ReclassifyRequest(classification="WORK")


class TestItemResponse:
    """Tests for ItemResponse model."""

    def test_wraps_item(self):
        item = Item(text="test")
        response = ItemResponse(item=item)
        assert response.item == item
        assert response.message == "success"


class TestItemsResponse:
    """Tests for ItemsResponse model."""

    def test_pagination_defaults(self):
        response = ItemsResponse(items=[], total=0)
        assert response.page == 1
        assert response.per_page == 50

    def test_with_items(self):
        items = [Item(text="test1"), Item(text="test2")]
        response = ItemsResponse(items=items, total=2, page=1, per_page=10)
        assert len(response.items) == 2
        assert response.total == 2
