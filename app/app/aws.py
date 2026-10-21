"""호환용 re-export. 구현은 app.core.aws로 옮겼다(D3).

B6 storage(app/app/core/storage/objects.py)와 test_storage.py가 `from app import aws`를 쓰므로 유지한다.
새 코드는 `from app.core import aws`를 쓴다.
"""
from app.core.aws import client

__all__ = ["client"]
