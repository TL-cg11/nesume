"""C — 공고·학습 콘텐츠 수집 배치 (cron 엔트리).

Helm `cronjob-jobs-collector`(D5)가 `python -m app.batch.jobs_collector`로 실행한다.
하루 1회 **서울시 공고·고용24 공채속보(C4)** 와 **K-MOOC·고용24 훈련과정(C14)** 을 수집해 upsert한다.
수집 로직은 각 기능에 있고(여기선 **배선·세션·커밋·로깅**만), API 키는 D가 Secrets로 주입한다:
  - 서울시: `SEOUL_OPENAPI_BASE_URL`, `SEOUL_OPENAPI_KEY`
  - K-MOOC: `KMOOC_API_KEY`, `KMOOC_API_BASE_URL`(기본값 있음)
  - 고용24: 훈련과정 `WORK24_TRAINING_API_KEY`, 공채속보 `WORK24_JOB_API_KEY`,
    공통 `WORK24_API_BASE_URL`(기본값 있음, https만)

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

SOURCES = ("seoul", "work24_open", "kmooc", "work24")


def collect_seoul(session: Session) -> dict:
    """서울시 공고 전량 재수집 → 건강성 게이트·upsert·사라짐 처리(C4)."""
    from app.postings.collect import fetch_all_seoul, run_collection

    rows = fetch_all_seoul()
    logger.info("seoul: fetched %d rows", len(rows))
    return run_collection(session, rows)


def collect_work24_open(session: Session) -> dict:
    """고용24 공채속보 전량(목록→상세) → 건강성 게이트·upsert·사라짐 처리(C4). 원문 링크 있는 출처."""
    from app.postings.collect import run_collection
    from app.postings.work24_open import SOURCE_WORK24_OPEN, fetch_all, http_fetch

    rows = fetch_all(http_fetch)
    logger.info("work24_open: fetched %d postings", len(rows))
    return run_collection(session, rows, source=SOURCE_WORK24_OPEN, parse=dict)


def collect_kmooc(session: Session) -> dict:
    """K-MOOC 강좌 전량 수집(list→detail 보강) → LearningContent upsert(C14)."""
    from app.features.roadmap.kmooc import collect, fetch_course_detail, fetch_list_page
    from app.features.roadmap.service import upsert_contents

    courses = collect(fetch_list_page, fetch_course_detail)
    logger.info("kmooc: collected %d courses", len(courses))
    return upsert_contents(session, courses)


def collect_work24(session: Session) -> dict:
    """고용24 훈련과정(역량 키워드별, 개강 예정분) → LearningContent upsert(C14). 약관상 화면 표시용 저장."""
    from app.features.roadmap.service import upsert_contents
    from app.features.roadmap.work24 import WORK24_SOURCE, collect, fetch_list_page

    courses = collect(fetch_list_page)
    logger.info("work24: collected %d courses", len(courses))
    return upsert_contents(session, courses, source=WORK24_SOURCE, mode="offline")


_RUNNERS: dict[str, Callable[[Session], dict]] = {
    "seoul": collect_seoul,
    "work24_open": collect_work24_open,
    "kmooc": collect_kmooc,
    "work24": collect_work24,
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
