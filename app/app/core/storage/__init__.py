"""B6 S3 비공개 저장 + 앱 경유 1회용 다운로드 (tasks B6 산출물 `core/storage`).

사용 예(B12 PDF):
    key = objects.user_object_key(user.sub, "resumes", str(resume_id), f"{doc_id}.pdf")
    objects.put_object(key, pdf_bytes, "application/pdf")
    token, expires_at = tokens.issue(db, user.sub, key, "자소서.pdf", "application/pdf")
    # 화면은 GET /downloads/{token}을 로그인 상태로 호출
"""
