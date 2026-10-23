"""B18 정상 질의 평가셋 형식 검사 (tasks.md B18, part2_guide 4.37·4.38).

평가셋은 저장소 최상위 `eval/scenarios/`(B 소유)에 있다. 테스트 컨테이너에 `/eval`로
읽기 전용 마운트돼야 읽힌다(D 요청). 마운트 전에는 건너뛴다.
측정(가드레일 투입)은 A가 A10과 같은 방식으로 한다.
"""
import os
import re
from pathlib import Path

import pytest
import yaml

EVAL_DIR = Path(os.environ.get("EVAL_DIR", "/eval"))
FILE = EVAL_DIR / "scenarios" / "b18_normal.yaml"

pytestmark = pytest.mark.skipif(not FILE.exists(), reason="eval/ 미마운트(D 요청 중)")

ROLES = {"user", "mentor", "operator"}
CURRENT_FEATURES = {"writing.proofread", "matching.analyze", "style.adjust"}
ID = re.compile(r"^B18-NORMAL-\d{2}$")


@pytest.fixture(scope="module")
def data() -> dict:
    with open(FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_counts(data):
    s = data["scenarios"]
    assert len(s) == 50
    tags = [t for x in s for t in x.get("tags", [])]
    assert tags.count("sensitive_word") == 20
    assert tags.count("own_pii") == 5


def test_well_formed(data):
    known_features = CURRENT_FEATURES | set(data["tentative_features"])
    seen = set()
    for x in data["scenarios"]:
        assert ID.match(x["id"]) and x["id"] not in seen, x["id"]
        seen.add(x["id"])
        assert x["category"] == "normal", x["id"]
        assert x["role"] in ROLES, x["id"]
        assert x["feature"] in known_features, x["id"]
        assert x["turns"] and all(t.strip() for t in x["turns"]), x["id"]
        assert x["expect"]["decision"] == "allow", x["id"]
        assert x.get("note"), f"{x['id']} 근거 없음"
        assert set(x.get("tags", [])) <= {"sensitive_word", "own_pii"}, x["id"]


def test_own_pii_checked_for_leak(data):
    # 본인 연락처 항목은 모델에 원문이 가지 않았는지까지 봐야 의미가 있다
    for x in data["scenarios"]:
        if "own_pii" in x.get("tags", []):
            secrets = x["expect"].get("prompt_free_of", [])
            assert secrets and all(s in x["turns"][-1] for s in secrets), x["id"]


def test_ids_sequential(data):
    assert [x["id"] for x in data["scenarios"]] == [f"B18-NORMAL-{i:02d}" for i in range(1, 51)]
