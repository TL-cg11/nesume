"""기능 패키지 루트.

각 팀은 이 아래에 features/<기능명>/ 패키지를 만들고 router.py에 APIRouter(prefix="/<기능명>")를 둔다.
라우터 등록은 app/app/main.py에서 명시적으로 한다(자동 등록·/v1 접두사 없음, web이 /api/<기능>을 호출).
main.py 등록은 D에 PR로 요청한다(커밋 메시지에 [D 리뷰 요청]). 규칙은 docs/dev/backend-guide.md 참조.
"""
