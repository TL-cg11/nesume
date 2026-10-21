"""PII 테스트 공통 설정.

PII 모듈은 DB·네트워크를 쓰지 않는다. 치환표는 InMemoryVaultStore 로 대체한다.
그래서 이 디렉터리에서는 테스트 DB를 만들지 않고, 상위 `tests/conftest.py` 의
세션 픽스처를 같은 이름으로 덮어써서 비활성화한다.

이렇게 두는 이유: 순수 로직 테스트가 Postgres 기동에 묶이면 되돌아오는 시간이 길어지고,
DB 없는 환경에서는 아예 돌지 않는다. A1은 다른 파트가 기다리는 모듈이라 검증이
빨라야 한다. (D·B 리뷰 요청 — 상위 하네스를 건드리지 않고 하위에서 덮는 방식이
팀 규칙에 맞는지 확인 부탁)
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def test_database():  # noqa: PT004 - 상위 픽스처를 덮기 위한 동명 픽스처
    yield


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
