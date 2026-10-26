# S3 문서 버킷 + PII용 KMS 키. 둘 다 base. 절대 destroy하지 않는다(KMS는 삭제 대기 7일).
# 키 정책은 기본값(계정 루트 kms:*)만 둔다. 역할별 허용은 modules/iam의 IAM 정책이 한다.
# (키 정책에 역할 ARN을 직접 넣으면 역할 생성 순서에 걸려 "invalid principals"가 난다.)
resource "aws_kms_key" "pii" {
  description             = "${var.name} PII: S3 docs SSE-KMS, app field encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "pii" {
  name          = "alias/${var.name}-pii"
  target_key_id = aws_kms_key.pii.key_id
}

resource "aws_s3_bucket" "docs" {
  bucket        = "${var.name}-docs-${var.account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "docs" {
  bucket = aws_s3_bucket.docs.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.pii.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "docs" {
  bucket                  = aws_s3_bucket.docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
