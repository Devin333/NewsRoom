from __future__ import annotations

import pytest

from framework.shared import PageRequest, PageResult


def test_page_request_validates_limit_and_serializes() -> None:
    request = PageRequest(limit=25, cursor=123)

    assert request.to_dict() == {"limit": 25, "cursor": "123"}
    with pytest.raises(ValueError):
        PageRequest(limit=0)
    with pytest.raises(ValueError):
        PageRequest(limit=501)


def test_page_result_has_more_and_serializes_items() -> None:
    page = PageResult(items=[{"id": 1}], next_cursor="next", total=10)

    assert page.has_more() is True
    assert page.to_dict(item_serializer=lambda item: {"value": item["id"]}) == {
        "items": [{"value": 1}],
        "next_cursor": "next",
        "total": 10,
    }


def test_page_result_without_cursor_has_no_more() -> None:
    assert PageResult(items=[]).has_more() is False
