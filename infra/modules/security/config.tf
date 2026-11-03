# D17 AWS Config — Security Hub FSBP 점검은 대부분 Config 기록으로 판정한다. 없으면 표준이 INCOMPLETE
# (11-03 apply 뒤 NO_AVAILABLE_CONFIGURATION_RECORDER 확인). docs/D17.md 결정10: 변경 즉시 기록(CONTINUOUS).
# 끄기(발표 뒤 비용): -var config_enabled=false 가 아니라 base 의 module "security" 에 config_enabled = false.

locals {
  config_count = var.config_enabled ? 1 : 0
}

# 서비스 연결 역할(AWSServiceRoleForConfig)은 Terraform 이 관리하지 않는다.
# 11-03 첫 apply 에서 만들어졌지만 provider default_tags 를 붙이는 iam:TagRole 권한이 없어 실패했다 →
# 역할은 AWS 에 남기고 state 에서만 뺀다(destroy = false). 경로는 AWS 가 정한 고정 값이다.
# 계정을 새로 만들 때는 한 번: aws iam create-service-linked-role --aws-service-name config.amazonaws.com
removed {
  from = aws_iam_service_linked_role.config

  lifecycle {
    destroy = false
  }
}

locals {
  config_role_arn = "arn:aws:iam::${var.account_id}:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig"
}

# 전용 버킷. CloudTrail 버킷(SSE-KMS)에 넣으면 트레일 키 정책·버킷 정책을 Config 용으로 넓혀야 한다 → 섞지 않는다.
# 설정 스냅숏에는 리소스 구성만 있고 PII·비밀은 없다 → SSE-S3. 발표 뒤 지울 수 있게 force_destroy.
#trivy:ignore:AVD-AWS-0089 버킷 접근 로그 없음(dev)
#trivy:ignore:AVD-AWS-0132 CMK 대신 SSE-S3(PII 없음)
resource "aws_s3_bucket" "config" {
  count         = local.config_count
  bucket        = "${var.name}-config-${var.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "config" {
  count                   = local.config_count
  bucket                  = aws_s3_bucket.config[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "config" {
  count  = local.config_count
  bucket = aws_s3_bucket.config[0].id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "config" {
  count  = local.config_count
  bucket = aws_s3_bucket.config[0].id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration { days = 30 }
  }
}

resource "aws_s3_bucket_policy" "config" {
  count  = local.config_count
  bucket = aws_s3_bucket.config[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ConfigAclCheck"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = ["s3:GetBucketAcl", "s3:ListBucket"]
        Resource  = aws_s3_bucket.config[0].arn
        Condition = { StringEquals = { "AWS:SourceAccount" = var.account_id } }
      },
      {
        Sid       = "ConfigWrite"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.config[0].arn}/AWSLogs/${var.account_id}/Config/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"      = "bucket-owner-full-control"
            "AWS:SourceAccount" = var.account_id
          }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.config[0].arn, "${aws_s3_bucket.config[0].arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })
}

resource "aws_config_configuration_recorder" "this" {
  count    = local.config_count
  name     = "${var.name}-recorder"
  role_arn = local.config_role_arn

  recording_group {
    all_supported                 = true
    include_global_resource_types = true # 리전이 서울 하나뿐(SCP)이라 IAM 같은 전역 리소스도 여기서
  }

  recording_mode {
    recording_frequency = "CONTINUOUS" # 결정10 B: 이틀 운영이면 매일 기록보다 싸고, 고친 것이 바로 재평가된다
  }
}

resource "aws_config_delivery_channel" "this" {
  count          = local.config_count
  name           = "${var.name}-delivery"
  s3_bucket_name = aws_s3_bucket.config[0].bucket

  depends_on = [aws_config_configuration_recorder.this, aws_s3_bucket_policy.config]
}

resource "aws_config_configuration_recorder_status" "this" {
  count      = local.config_count
  name       = aws_config_configuration_recorder.this[0].name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.this]
}
