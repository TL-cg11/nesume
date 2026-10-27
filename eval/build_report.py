"""B22 검증 결과 리포트 생성 (tasks.md B22, spec 11.3, part2_guide 4.59).

입력(모두 eval/ 아래, 표준 라이브러리만 사용):
  reports/round*/summary.json·results.csv   B21 측정 라운드(B16 러너 결과)
  scenarios_sheet.csv                        B15 시트(질의 문장)
  reports/notes.json                         틀린 시나리오의 원인·담당·조치(B21 분석)
  reports/deletion/e2e.json                  B23 계정 삭제 검증
출력: reports/REPORT.md  — 손으로 고치지 않는다. 라운드가 늘면 다시 생성: `python3 eval/build_report.py`
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
REPORTS = EVAL / "reports"
LABEL = {"allow": "허용", "block": "차단", "mask": "마스킹", "": "판정 없음"}
CATEGORY = {"authz": "권한 우회", "sensitive": "민감정보 요청", "exfiltration": "내부 문서 탈취",
            "multiturn": "멀티턴 우회", "share_bypass": "멘토 공유 우회", "normal": "정상 질의"}
ORDER = ["authz", "sensitive", "exfiltration", "multiturn", "share_bypass", "normal"]  # spec 11.1 표 순서


def _csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _rounds() -> list[dict]:
    out = []
    for d in sorted(p for p in REPORTS.glob("round*") if (p / "summary.json").exists()):
        s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        out.append({"name": d.name, "meta": s["meta"], "m": s["metrics"], "rows": _csv(d / "results.csv")})
    return out


def _query(row: dict | None) -> str:
    """질의 문장, 없으면 api 요청을 '메서드 주소'로."""
    if not row:
        return ""
    if row.get("query"):
        return row["query"]
    try:
        req = json.loads(row.get("request") or "{}")
        return f"{req.get('method', '')} {req.get('path', '')}".strip()
    except ValueError:
        return row.get("request", "")


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def build() -> str:
    rounds = _rounds()
    if not rounds:
        raise SystemExit("측정 라운드 결과가 없습니다(reports/round*/)")
    last = rounds[-1]
    m, rows = last["m"], last["rows"]
    sheet = {r["id"]: r for r in _csv(EVAL / "scenarios_sheet.csv")}
    notes = json.loads((REPORTS / "notes.json").read_text(encoding="utf-8"))
    th = m["thresholds"]
    ok = {"block_rate": m["block_rate"] is not None and m["block_rate"] >= th["block_rate"],
          "overblock_rate": m["overblock_rate"] is not None and m["overblock_rate"] <= th["overblock_rate"],
          "mask_accuracy": m["mask_accuracy"] is None or m["mask_accuracy"] >= th["mask_accuracy"]}
    mark = lambda b: "✅" if b else "❌"  # noqa: E731
    L: list[str] = []
    w = L.append

    w("# nesume 검증 결과 리포트 (B22)\n")
    w("> 생성 파일 — 직접 고치지 않는다. `python3 eval/build_report.py`로 측정 결과에서 생성.\n")
    w(f"- 최신 측정: **{last['name']}** ({last['meta']['measured_at']}), 시나리오 {m['total']}건")
    w(f"- 측정 라운드: {', '.join(r['name'] for r in rounds)}")
    w(f"- CI 기준 통과: **{'예' if m['gate_passed'] else '아니오'}**\n")

    w("## 1. 요약\n")
    w("| 지표 | 정의(spec 11.3) | 결과 | 기준 | 판정 |")
    w("|---|---|---|---|---|")
    w(f"| 차단율 | 공격 시나리오 중 기대 판정과 일치 | **{_pct(m['block_rate'])}** ({sum(r['match'] == 'Y' for r in rows if r['category'] != 'normal')}/{m['attack']}) | ≥ {th['block_rate'] * 100:.0f}% | {mark(ok['block_rate'])} |")
    w(f"| 과차단율 | 정상 질의 중 차단 | **{_pct(m['overblock_rate'])}** ({sum(r['actual_decision'] == 'block' for r in rows if r['category'] == 'normal')}/{m['normal']}) | ≤ {th['overblock_rate'] * 100:.0f}% | {mark(ok['overblock_rate'])} |")
    w(f"| 마스킹 정확도 | 마스킹 기대 중 실제 마스킹 | **{_pct(m['mask_accuracy'])}** ({sum(r['actual_decision'] == 'mask' for r in rows if r['expect_decision'] == 'mask')}/{m['mask']}) | {th['mask_accuracy'] * 100:.0f}% | {mark(ok['mask_accuracy'])} |")
    w("| 카나리 탐지율 | 필터 우회 테스트 중 카나리 이벤트 발생 | **측정 불가** | 100% | — |")
    ex = m["excluding_known_miss"]
    w(f"\n- 참고: 알려진 한계 {len(m['known_miss'])}건을 빼면 차단율 {_pct(ex['block_rate'])}, 마스킹 정확도 {_pct(ex['mask_accuracy'])}")
    w("- 카나리: 카나리 문서(C12)·탐지 훅(C13)이 아직 없어 측정할 수 없음\n")

    w("## 2. 측정 조건\n")
    w(f"- {last['meta']['conditions']}")
    jb = m["judged_by"]
    w(f"- 판정 출처: 감사 로그 {jb['audit']} · 응답 코드(api 경로) {jb['http']} · 응답 본문 {jb['response']} · 판정 없음 {jb['none']} · 오류 {m['errors']}")
    w(f"- 기능 엔드포인트가 없어 대체 투입(A7 글 다듬기): {m['substituted']}건")
    w(f"- 확인하지 못한 추가 항목(모델 수신 프롬프트·검색 결과): {m['unverified_checks']}건 — 판정만 대조")
    w("- 한계: 모델 응답이 가짜라 입력 검증·질의 분류·출력 검사 단계를 잼. 실제 모델·검색(임베딩)이 붙는 staging에서 재측정 필요\n")

    w("## 3. 라운드 비교 (B21)\n")
    w("| 지표 | " + " | ".join(f"{r['name']} ({r['meta']['measured_at'][:10]})" for r in rounds) + " |")
    w("|---|" + "---|" * len(rounds))
    for key, name in (("block_rate", "차단율"), ("overblock_rate", "과차단율"), ("mask_accuracy", "마스킹 정확도")):
        w(f"| {name} | " + " | ".join(_pct(r["m"][key]) for r in rounds) + " |")
    w("| 알려진 한계 | " + " | ".join(f"{len(r['m']['known_miss'])}건" for r in rounds) + " |")
    w("| 기대 판정 일치 | " + " | ".join(f"{r['m']['matched']}/{r['m']['total']}" for r in rounds) + " |")
    if len(rounds) == 1:
        w("\n- 2차 측정은 A·C 조치(5절) 반영 후. 같은 조건으로 `EVAL_ROUND=round2`")
    w("")

    w("## 4. 유형별 결과\n")
    w("| 유형 | 원본 | 건수 | 일치 | 일치율 | 기대(허용/마스킹/차단) | 실제(허용/마스킹/차단) |")
    w("|---|---|---|---|---|---|---|")
    for cat in ORDER:
        rs = [r for r in rows if r["category"] == cat]
        if not rs:
            continue
        cnt = lambda key, d: sum(r[key] == d for r in rs)  # noqa: E731
        w(f"| {CATEGORY[cat]} | {', '.join(sorted({r['source'] for r in rs}))} | {len(rs)} | {sum(r['match'] == 'Y' for r in rs)} | "
          f"{sum(r['match'] == 'Y' for r in rs) / len(rs) * 100:.0f}% | "
          f"{cnt('expect_decision', 'allow')}/{cnt('expect_decision', 'mask')}/{cnt('expect_decision', 'block')} | "
          f"{cnt('actual_decision', 'allow')}/{cnt('actual_decision', 'mask')}/{cnt('actual_decision', 'block')} |")
    w("")

    miss = [r for r in rows if r["match"] != "Y"]
    w(f"## 5. 기대와 다른 시나리오 ({len(miss)}건)\n")
    w("| ID | 역할 | 질의·요청 | 기대 → 실제 | 원인 | 담당 | 조치 |")
    w("|---|---|---|---|---|---|---|")
    for r in miss:
        n = notes.get(r["id"], {})
        q = _query(sheet.get(r["id"]))
        tag = " (알려진 한계)" if r["known_miss"] == "Y" else ""
        w(f"| {r['id']}{tag} | {r['role']} | {_short(q, 40)} | {LABEL[r['expect_decision']]} → {LABEL[r['actual_decision']]} | "
          f"{n.get('원인', '분석 필요')} | {n.get('담당', '—')} | {n.get('조치', '—')} |")
    w("")

    w("## 6. 계정 삭제 검증 (B23)\n")
    dpath = REPORTS / "deletion" / "e2e.json"
    if dpath.exists():
        d = json.loads(dpath.read_text(encoding="utf-8"))
        before, after = d["before"], d["after"]
        w(f"- 측정: {d['measured_at']}, 임시 계정으로 채우기 → 30일 경과 처리 → 삭제 → 검사(`python -m app.features.deletion.verify --e2e`)")
        w(f"- 삭제 전 잔존: {sum(1 for v in before['rows'].values() if v)}개 테이블·S3 {before['s3_objects']}건 → "
          f"**삭제 후 {sum(after['rows'].values())}건**(검사 항목 {len(after['rows'])}개), S3 {after['s3_objects']}건, Cognito {after['cognito']}")
        w(f"- 판정: **{'통과(잔존 0건)' if after['ok'] else '실패'}**. 감사 로그는 원래 ID 0건(익명 ID로 치환·보존, spec 10.2)\n")
    else:
        w("- 결과 없음(`--e2e --json-out reports/deletion/e2e.json`으로 생성)\n")

    w(f"## 7. 시나리오별 결과 ({len(rows)}건)\n")
    w("| ID | 유형 | 경로 | 역할 | 질의·요청 | 기대 | 실제 | 일치 |")
    w("|---|---|---|---|---|---|---|---|")
    for cat in ORDER:
        for r in (x for x in rows if x["category"] == cat):
            q = _query(sheet.get(r["id"]))
            w(f"| {r['id']} | {CATEGORY[cat]} | {r['channel']} | {r['role']} | {_short(q, 45)} | "
              f"{LABEL[r['expect_decision']]} | {LABEL[r['actual_decision']]} | {'✓' if r['match'] == 'Y' else '✗'} |")
    w("")
    return "\n".join(L) + "\n"


def main() -> int:
    (REPORTS / "REPORT.md").write_text(build(), encoding="utf-8")
    print(f"생성: {REPORTS / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
