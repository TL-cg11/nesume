# 데이터 모델 (B1, B2)

마이그레이션: `0002` B1 핵심 테이블, `0003` B2 문서 등급·공유 컬럼, `0004` B4 복원 출처
소유: B (모델 추가는 B가 취합, tasks.md 디렉터리 소유). **C·D 리뷰 요청 대상.**

## ERD

```mermaid
erDiagram
    users ||--o{ resumes : owns
    users ||--o{ experiences : owns
    users ||--o{ applications : owns
    users ||--o{ shares : "owner / shared_with"
    resumes ||--o{ questions : has
    questions ||--o{ versions : has
    resumes ||--o{ shares : shared
    resumes |o--o{ applications : "SET NULL"

    users {
        string id PK "Cognito sub"
        string anon_id UK "계정 삭제 시 발급(spec 10.2)"
        timestamptz deleted_at
    }
    resumes {
        uuid id PK
        string owner_id FK
        string title
        uuid job_posting_id "C4 공고 내부 ID, FK는 C가 추가"
        string status "값 미정(제약 없음)"
        string grade "personal"
        jsonb shared_with "[{user_id, expires_at}] (B2)"
        timestamptz deleted_at "소프트 삭제"
    }
    questions {
        uuid id PK
        uuid resume_id FK
        text title
        int char_limit
        int position
        string grade "personal"
    }
    versions {
        uuid id PK
        uuid question_id FK
        int version_no "문항별 유일"
        text body "B7에서 암호화 전환"
        int char_count
        string source "manual | ai"
        bool compressed
        uuid restored_from "복원 원본 버전(B4), FK 없음"
        string grade "personal"
    }
    experiences {
        uuid id PK
        string owner_id FK
        string type "값 미정(제약 없음)"
        string[] tech_stack
        string[] tags "GIN"
        text outcome "B7에서 암호화 전환"
        text detail "B7에서 암호화 전환"
        string grade "personal"
    }
    shares {
        uuid id PK
        uuid resume_id FK
        string shared_with FK
        timestamptz expires_at
        timestamptz revoked_at
    }
    applications {
        uuid id PK
        string owner_id FK
        uuid job_posting_id
        uuid resume_id FK
        uuid[] version_ids "지원 시점 문항별 버전"
        string status "applied | document_passed | interview | final | rejected"
        string grade "personal"
    }
    templates {
        uuid id PK
        string name "name+version 유일, 활성 1개"
        int version
        bool is_active
        jsonb variables
        string grade "internal"
    }
    audit_logs {
        uuid request_id PK
        string user_id "FK 없음, 삭제 시 anon_id 치환"
        string role
        string decision "allow | block | mask"
        string[] flags
        bool is_test
        string grade "sensitive"
    }
```

## 규칙

| 규칙 | 구현 | 근거 |
|---|---|---|
| 모든 ID는 UUID(서버 기본값 `gen_random_uuid()`), 사용자 ID만 Cognito sub 문자열 | `_common.UuidPk` | |
| 하위 테이블에도 `owner_id` 저장 | `_common.owner_fk()` | spec 3.1 "owner_id 필수" |
| 사용자 물리 삭제 시 소유 문서 CASCADE | `owner_id ... ON DELETE CASCADE` | B20 |
| 감사 로그는 사용자 삭제 후에도 보존 | `audit_logs.user_id` FK 없음 | spec 10.2 |
| 버전은 INSERT 전용 | `versions_immutable` 트리거 | spec 3.1 "덮어쓰지 않음" |
| 지원 기록은 지원 시점 버전을 고정 참조 | `applications.version_ids` (문항별 버전 ID 배열) | spec 4.5 |
| 지원 기록은 자소서 삭제 후에도 유지 | `applications.resume_id` SET NULL | spec 4.5 |
| 이름별 활성 템플릿 1개 | 부분 유일 인덱스 `uq_templates_active_name` | spec 3.6 |
| 문서 등급 5종, 테이블별 기본값 | `_common.Grade`, CHECK 제약 | spec 6.2, 6.4 (B2) |
| 공유 대상·멘토별 만료 | `resumes.shared_with` JSONB 배열, 원본은 `shares` (B10에서 동기화) | tasks B2, spec 3.7 |
| 값 목록이 문서에 정의된 컬럼만 CHECK 제약 | `_common.one_of()` | versions.source, applications.status, audit_logs 등 |

### 테이블별 기본 등급 (spec 6.4)

| 등급 | 테이블 |
|---|---|
| personal | resumes, questions, versions, experiences, applications |
| internal | templates |
| sensitive | audit_logs |

ORM을 거치지 않는 INSERT에도 DB 기본값으로 같은 등급이 붙는다. 클라이언트 입력으로 등급을 바꾸지 못하게 하는 것은 B8.

## 구현용 보조 요소 (문서 기능을 구현하기 위해 추가)

| 요소 | 용도 | 관련 문서 |
|---|---|---|
| `users.anon_id` | 계정 삭제 시 감사 로그 user_id를 치환할 익명화 토큰 | spec 10.2 |
| `questions.position` | 문항 표시 순서 | spec 3.1 |
| `versions.version_no`, `char_count` | 버전 번호, 글자 수 제한 비교 | spec 3.1 |
| `versions.compressed` | 50개 초과 시 압축된 보관 요약 행 표시 | spec 3.1 |
| `versions.restored_from` | 이전 버전 복원 시 원본 버전 ID. UPDATE 금지 트리거와 FK 연쇄(SET NULL)가 충돌해 FK 없음 | spec 3.1 (B4) |
| `templates.created_by` | 템플릿 수정 이력(작성 운영자) | spec 3.6 |
| `shares` 부분 인덱스 `ix_shares_active_lookup` | 멘토별 유효 공유 조회 | spec 3.7 |

## 후속 태스크에서 처리

| 태스크 | 변경 |
|---|---|
| B4 | 버전 압축 시 `applications.version_ids`가 참조하는 버전 제외(배열은 FK 보호 불가) |
| B3 | 감사 로그 테이블 권한(앱 계정 INSERT·SELECT만), 보관 기간 정리 |
| B7 | `user_keys`, `pii_token_map`, 본문·경험 컬럼 암호화 전환 |
| B10 | `shares` ↔ `resumes.shared_with` ↔ 벡터 메타데이터 동기화 |
| B12·B13 | PDF·면접 연습 테이블 |
| B20 | 삭제 작업 테이블 |
| C4 | 공고 테이블 + `resumes.job_posting_id`, `applications.job_posting_id` FK |

## 팀 확정 필요

| 항목 | 현재 상태 |
|---|---|
| `resumes.status` 값 목록 | 문서에 없음 → 제약 없음 |
| `experiences.type` 값 목록 | 문서는 예시만(프로젝트·활동·수상 등) → 제약 없음 |
| 역할·등급 명칭 (D1) | `user/mentor/operator/system`, `public/internal/personal/sensitive/confidential` 잠정 |

## 리뷰 요청 사항

- **C**: `applications` 컬럼·상태값, `version_ids` 참조 방식, 공고 FK 추가 시점, `resumes.shared_with` 형식(벡터 메타데이터 반영 C3)
- **D**: 역할·등급 명칭과 D1 일치 여부, `app/app/db.py` 이름 규칙 변경
