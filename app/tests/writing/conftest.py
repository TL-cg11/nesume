"""글 교정 테스트 공통 설정.

A 파트 모듈은 DB·네트워크를 쓰지 않으므로 상위 하네스의 세션 픽스처를 비활성화한다.
(tests/pii/·tests/guardrail/ 과 같은 방식 — D·B 확인 요청 중)
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def test_database():  # noqa: PT004
    yield


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
