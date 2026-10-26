"""B16 평가 러너 실행: `PYTHONPATH=/eval python -m runner --base-url http://app:8000`.

결과: --out-dir에 results-<시각>.csv·summary-<시각>.json. CI 기준 미달이면 종료 코드 1(D11 게이트).
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from runner import core
from runner.accounts import CognitoAccounts
from runner.seed import DbSeeder


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="B16 평가 러너")
    p.add_argument("--base-url", required=True)
    p.add_argument("--sheet", type=Path, default=Path(__file__).resolve().parent.parent / "scenarios_sheet.yaml")
    p.add_argument("--out-dir", type=Path, default=Path("."))
    p.add_argument("--only", default="", help="쉼표로 ID 접두어 필터(예: B19,C11)")
    p.add_argument("--delay", type=float, default=0.05)
    a = p.parse_args(argv)

    scenarios = core.load_sheet(a.sheet)
    if a.only:
        prefixes = tuple(x.strip() for x in a.only.split(",") if x.strip())
        scenarios = [s for s in scenarios if s["id"].startswith(prefixes)]
    accounts = CognitoAccounts.from_env()
    with httpx.Client(base_url=a.base_url, timeout=60) as client:
        results, m = core.run(client, accounts, DbSeeder(accounts), scenarios, delay=a.delay)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / f"results-{stamp}.csv").write_text(core.render_csv(results), encoding="utf-8")
    (a.out_dir / f"summary-{stamp}.json").write_text(core.render_summary(m), encoding="utf-8")
    print(core.render_summary(m))
    return 0 if m["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
