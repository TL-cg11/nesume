"""B15 검증 시나리오 취합 (tasks.md B15, spec 11.1, part2_guide 4.48).

각 팀 원본(YAML)은 제자리에 두고, 이 스크립트가 읽어서 단일 시트를 만든다.
  - eval/scenarios_sheet.yaml  평가 러너(B16)·테스트가 읽는 원본 형식
  - eval/scenarios_sheet.csv   사람이 보는 생성본(엑셀·노션·리포트). 손으로 고치지 않는다

시트를 고치려면 각 원본을 고친 뒤 다시 생성한다. tests/test_eval_sheet.py가 생성본이 원본과 같은지 확인한다.

생성(테스트 컨테이너, eval/을 쓰기 가능하게 한 번 더 마운트):
    docker compose run --rm -v "$PWD/eval:/eval_rw" --entrypoint python test \\
        /eval/build_sheet.py --app-dir /srv --eval-dir /eval --out-dir /eval_rw
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path

import yaml

# (태스크, 기준 디렉터리, 상대 경로, 필수 여부). 순서가 시트 순서다(spec 11.1 표 순서)
SOURCES = [
    ("C11", "eval", "scenarios/c11_authz.yaml", False),  # 권한 우회 10건. C 제출 대기(위치는 C와 확정)
    ("A10", "app", "tests/guardrail/scenarios_a10.yaml", True),  # 민감정보 10·탈취 10·멀티턴 5
    ("B19", "eval", "scenarios/b19_share.yaml", True),  # 멘토 공유 우회 5
    ("B18", "eval", "scenarios/b18_normal.yaml", True),  # 정상 질의 50
]
EXPECTED_COUNTS = {"C11": 10, "A10": 25, "B19": 5, "B18": 50}  # tasks.md
DECISIONS = ("allow", "block", "mask")
ID = re.compile(r"^(?P<task>[A-D]\d+)-[A-Z]+-\d{2}$")

CSV_COLUMNS = [
    "id", "source", "category", "channel", "role", "feature", "query", "request", "preconditions",
    "expect_decision", "expect_message", "expect_checks", "known_miss", "note",
]


class SheetError(ValueError):
    pass


def _dump(value) -> str:
    """CSV 칸에 넣을 짧은 JSON. 비어 있으면 빈 칸."""
    if value in (None, {}, []):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def normalize(task: str, s: dict) -> dict:
    """팀별 원본 항목을 시트 한 행으로. 원본에 없는 칸은 비워 둔다."""
    expect = dict(s.get("expect") or {})
    decision = expect.pop("decision", None)
    message = expect.pop("message", None)
    return {
        "id": s.get("id"),
        "source": task,
        "category": s.get("category"),
        "channel": s.get("channel", "llm"),  # A10·B18은 모두 AI 질의
        "role": s.get("role"),
        "feature": s.get("feature"),  # A10에는 아직 없음(B15 정리 대상)
        "turns": list(s.get("turns") or []),
        "request": s.get("request"),
        "preconditions": s.get("preconditions") or {},
        "expect_decision": decision,
        "expect_message": message,
        "expect_checks": expect,  # query_type·flags_include·prompt_free_of·http_status·retrieval_excludes 등
        "known_miss": bool(s.get("known_miss", False)),
        "tags": list(s.get("tags") or []),
        "note": (s.get("note") or "").strip(),
    }


def validate(rows: list[dict], loaded: dict[str, int]) -> None:
    seen: set[str] = set()
    for r in rows:
        rid = r["id"] or "?"
        m = ID.match(rid)
        if not m or m.group("task") != r["source"]:
            raise SheetError(f"ID 형식 또는 태스크 불일치: {rid} ({r['source']})")
        if rid in seen:
            raise SheetError(f"ID 중복: {rid}")
        seen.add(rid)
        if r["expect_decision"] not in DECISIONS:
            raise SheetError(f"기대 판정은 allow/block/mask만: {rid}")
        if not r["role"] or not r["note"]:
            raise SheetError(f"역할·근거 필수: {rid}")
        if r["channel"] == "api":
            if not r["request"] or r["turns"]:
                raise SheetError(f"api 경로는 request만: {rid}")
        elif r["channel"] == "llm":
            if not r["turns"] or r["request"]:
                raise SheetError(f"llm 경로는 turns만: {rid}")
        else:
            raise SheetError(f"경로는 api/llm만: {rid}")
    for task, n in loaded.items():
        if n != EXPECTED_COUNTS[task]:
            raise SheetError(f"{task} 건수 {n} != {EXPECTED_COUNTS[task]}(tasks.md)")


def build(app_dir: Path, eval_dir: Path) -> dict:
    bases = {"app": app_dir, "eval": eval_dir}
    rows: list[dict] = []
    loaded: dict[str, int] = {}
    missing: list[str] = []
    for task, base, rel, required in SOURCES:
        path = bases[base] / rel
        if not path.exists():
            if required:
                raise SheetError(f"원본 없음: {base}/{rel}")
            missing.append(f"{task} ({base}/{rel})")
            continue
        with open(path, encoding="utf-8") as f:
            items = yaml.safe_load(f)["scenarios"]
        loaded[task] = len(items)
        rows.extend(normalize(task, s) for s in items)
    validate(rows, loaded)
    summary = {
        "total": len(rows),
        "by_source": loaded,
        "by_decision": {d: sum(r["expect_decision"] == d for r in rows) for d in DECISIONS},
        "by_channel": {c: sum(r["channel"] == c for r in rows) for c in ("api", "llm")},
        "known_miss": sum(r["known_miss"] for r in rows),
        "missing_sources": missing,
        "feature_missing": sum(not r["feature"] for r in rows),
    }
    return {"version": 1, "summary": summary, "scenarios": rows}


def render_yaml(sheet: dict) -> str:
    head = "# 생성 파일 — 직접 고치지 않는다. eval/build_sheet.py로 각 팀 원본에서 생성(B15)\n"
    return head + yaml.safe_dump(sheet, allow_unicode=True, sort_keys=False, width=1000)


def render_csv(sheet: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in sheet["scenarios"]:
        w.writerow({
            "id": r["id"], "source": r["source"], "category": r["category"], "channel": r["channel"],
            "role": r["role"], "feature": r["feature"] or "",
            "query": "\n".join(f"{i}) {t}" for i, t in enumerate(r["turns"], 1)) if len(r["turns"]) > 1
            else (r["turns"][0] if r["turns"] else ""),
            "request": _dump(r["request"]), "preconditions": _dump(r["preconditions"]),
            "expect_decision": r["expect_decision"], "expect_message": r["expect_message"] or "",
            "expect_checks": _dump(r["expect_checks"]), "known_miss": "Y" if r["known_miss"] else "",
            "note": r["note"],
        })
    return "﻿" + buf.getvalue()  # 엑셀에서 한글이 깨지지 않도록 BOM


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description="B15 시나리오 시트 생성")
    p.add_argument("--app-dir", type=Path, default=root / "app")
    p.add_argument("--eval-dir", type=Path, default=root / "eval")
    p.add_argument("--out-dir", type=Path, default=None, help="기본은 --eval-dir")
    a = p.parse_args()
    sheet = build(a.app_dir, a.eval_dir)
    out = a.out_dir or a.eval_dir
    (out / "scenarios_sheet.yaml").write_text(render_yaml(sheet), encoding="utf-8")
    (out / "scenarios_sheet.csv").write_text(render_csv(sheet), encoding="utf-8")
    s = sheet["summary"]
    print(f"시나리오 {s['total']}건 {s['by_source']} / 누락 원본: {s['missing_sources'] or '없음'}")


if __name__ == "__main__":
    main()
