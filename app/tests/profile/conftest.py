"""A14 테스트 공통 설정.

추출·조립은 DB 를 쓰지 않으므로 상위 하네스의 세션 픽스처를 비활성화한다.
(tests/pii/·tests/guardrail/ 과 같은 방식) DB 저장소(`DbProfileStore`) 자체는
B 의 마이그레이션이 올라간 뒤 통합 테스트로 확인한다.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def test_database():  # noqa: PT004
    yield
