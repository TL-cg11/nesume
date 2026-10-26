"""ORM 모델 (B 소유, 모델 추가는 B가 취합). Alembic autogenerate가 이 패키지를 import한다."""
from app.models.application import Application
from app.models.audit import AuditLog
from app.models.download import DownloadToken
from app.models.embedding import JobPostingEmbedding, UserProfileEmbedding
from app.models.experience import Experience, QuestionExperience
from app.models.learning import LearningContent, LearningRoadmap, LearningRoadmapItem
from app.models.pii import PiiVault, UserKey
from app.models.posting import CollectionRun, JobPosting
from app.models.resume import Question, Resume, Version
from app.models.share import Share
from app.models.share_comment import ShareComment
from app.models.template import PromptTemplate
from app.models.user import User
from app.models.writing_profile import WritingProfile

# 등급 자동 부여 훅 등록(B8). 모델 import 뒤에 둔다.
from app.models import grading  # noqa: E402,F401

__all__ = [
    "Application",
    "AuditLog",
    "CollectionRun",
    "DownloadToken",
    "Experience",
    "JobPosting",
    "JobPostingEmbedding",
    "LearningContent",
    "LearningRoadmap",
    "LearningRoadmapItem",
    "PiiVault",
    "PromptTemplate",
    "QuestionExperience",
    "Question",
    "Resume",
    "Share",
    "ShareComment",
    "User",
    "UserKey",
    "UserProfileEmbedding",
    "Version",
    "WritingProfile",
]
