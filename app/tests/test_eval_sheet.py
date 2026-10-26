"""B15 시나리오 시트: 생성본(YAML·CSV)이 각 팀 원본과 같은지, 시트 규칙을 지키는지 (part2_guide 4.48).

원본을 고치고 시트를 다시 생성하지 않으면 실패한다. 생성 방법은 eval/build_sheet.py 맨 위 주석.
"""
import csv
import importlib.util
import io
import os
from pathlib import Path

import pytest

EVAL = Path(os.environ.get("EVAL_DIR", "/eval"))
APP = Path("/srv")
pytestmark = pytest.mark.skipif(not (EVAL / "build_sheet.py").exists(), reason="eval/ 미마운트")


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("build_sheet", EVAL / "build_sheet.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def sheet(mod):
    return mod.build(APP, EVAL)


def test_generated_files_are_up_to_date(mod, sheet):
    assert (EVAL / "scenarios_sheet.yaml").read_text(encoding="utf-8") == mod.render_yaml(sheet), \
        "scenarios_sheet.yaml이 원본과 다릅니다. build_sheet.py로 다시 생성하세요"
    assert (EVAL / "scenarios_sheet.csv").read_text(encoding="utf-8") == mod.render_csv(sheet), \
        "scenarios_sheet.csv가 원본과 다릅니다. build_sheet.py로 다시 생성하세요"


def test_summary(sheet):
    s = sheet["summary"]
    assert s["by_source"] == {"A10": 25, "B19": 5, "B18": 50}  # C11 제출 후 10 추가
    assert s["total"] == 80 and s["missing_sources"] == ["C11 (eval/scenarios/c11_authz.yaml)"]


def test_csv_is_excel_friendly_and_one_row_per_scenario(mod, sheet):
    text = mod.render_csv(sheet)
    assert text.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    assert [r["id"] for r in rows] == [r["id"] for r in sheet["scenarios"]]
    assert set(rows[0]) == set(mod.CSV_COLUMNS)
    multi = next(r for r in rows if r["id"].startswith("A10-MULTI"))
    assert multi["query"].startswith("1) ")  # 여러 턴은 번호를 붙여 한 칸에


@pytest.mark.parametrize("bad,msg", [
    ({"id": "A10-SENS-01"}, "ID 중복"),
    ({"id": "B99-X-01"}, "태스크 불일치"),
    ({"expect_decision": "flag"}, "allow/block/mask"),
    ({"note": ""}, "근거"),
    ({"channel": "api"}, "api 경로"),
])
def test_validation_rejects(mod, sheet, bad, msg):
    rows = [dict(r) for r in sheet["scenarios"]]
    rows.append({**rows[0], "id": "A10-SENS-99", **bad})
    with pytest.raises(mod.SheetError, match=msg):
        mod.validate(rows, sheet["summary"]["by_source"])


def test_missing_required_source_fails(mod, tmp_path):
    with pytest.raises(mod.SheetError, match="원본 없음"):
        mod.build(tmp_path, EVAL)
