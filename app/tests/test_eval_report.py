"""B22 리포트가 측정 결과와 같은지(생성 파일 최신 여부)와 핵심 수치 (part2_guide 4.59)."""
import importlib.util
from pathlib import Path

import pytest

EVAL = Path("/eval")
pytestmark = pytest.mark.skipif(not (EVAL / "build_report.py").exists(), reason="eval/ 미마운트")


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("build_report", EVAL / "build_report.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_report_is_up_to_date(mod):
    assert (EVAL / "reports" / "REPORT.md").read_text(encoding="utf-8") == mod.build(), \
        "REPORT.md가 측정 결과와 다릅니다. python3 eval/build_report.py로 다시 생성하세요"


def test_report_has_required_sections(mod):
    text = mod.build()
    for section in ("차단율", "과차단율", "마스킹 정확도", "카나리 탐지율", "유형별 결과", "기대와 다른 시나리오",
                    "계정 삭제 검증", "시나리오별 결과"):
        assert section in text, section
    assert text.count("\n| ") >= 90  # 시나리오별 표 포함
