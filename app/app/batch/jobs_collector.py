"""C — 공고·학습 콘텐츠 수집 배치 (cron 엔트리).

Helm `cronjob-jobs-collector`(D5)가 `python -m app.batch.jobs_collector`로 실행한다.
하루 1회 **서울시 공고(C4)** 와 **K-MOOC 학습 콘텐츠(C14)** 를 전량 수집해 DB에 upsert한다.
수집 로직은 각 기능에 있고(여기선 **배선·세션·커밋·로깅**만), API 키는 D가 Secrets로 주입한다:
  - 서울시: `SEOUL_OPENAPI_BASE_URL`, `SEOUL_OPENAPI_KEY`
  - K-MOOC: `KMOOC_API_KEY`, `KMOOC_API_BASE_URL`(기본값 있음)

소스별로 **독립 트랜잭션**(하나 실패해도 다른 하나는 반영). 하나라도 실패하면 종료코드 1
(cron이 실패로 인지). 네트워크·DB가 필요해 로컬 단위테스트 대상이 아니다(실행은 운영/CI).
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db import SessionLocal

logger = logging.getLogger("app.batch.jobs_collector")

SOURCES = ("seoul", "kmooc")


def collect_seoul(session: Session) -> dict:
    """서울시 공고 전량 재수집 → 건강성 게이트·upsert·사라짐 처리(C4)."""
    from app.postings.collect import fetch_all_seoul, run_collection

    rows = fetch_all_seoul()
    logger.info("seoul: fetched %d rows", len(rows))
    return run_collection(session, rows)


def collect_kmooc(session: Session) -> dict:
    """K-MOOC 강좌 전량 수집(list→detail 보강) → LearningContent upsert(C14)."""
    from app.features.roadmap.kmooc import collect, fetch_course_detail, fetch_list_page
    from app.features.roadmap.service import upsert_contents

    courses = collect(fetch_list_page, fetch_course_detail)
    logger.info("kmooc: collected %d courses", len(courses))
    return upsert_contents(session, courses)


_RUNNERS: dict[str, Callable[[Session], dict]] = {
    "seoul": collect_seoul,
    "kmooc": collect_kmooc,
}


def _run_one(source: str) -> bool:
    """한 소스를 자체 세션·트랜잭션으로 수집. 성공 True / 실패 False(로그 남김)."""
    session = SessionLocal()
    try:
        summary = _RUNNERS[source](session)
        session.commit()
        logger.info("%s: done %s", source, summary)
        return True
    except Exception:  # noqa: BLE001 - 한 소스 실패가 다른 소스를 막지 않게 가둔다
        session.rollback()
        logger.exception("%s: FAILED", source)
        return False
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공고·학습 콘텐츠 수집 배치")
    parser.add_argument(
        "--source", choices=[*SOURCES, "all"], default="all", help="수집 소스(기본 all)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    targets = list(SOURCES) if args.source == "all" else [args.source]
    results = {s: _run_one(s) for s in targets}

    failed = [s for s, ok in results.items() if not ok]
    if failed:
        logger.error("일부 소스 실패: %s", failed)
        return 1
    logger.info("수집 완료: %s", targets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
