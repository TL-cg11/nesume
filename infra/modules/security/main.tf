# D17 계정 보안 서비스: CloudTrail · GuardDuty(EKS 보호 포함) · Security Hub (spec 276행).
# base 레이어에 둔다 — compute 를 내려도 계정 감시는 꺼지면 안 된다. 계정·리전당 하나씩만 있을 수 있는 리소스다.
# 결정(docs/D17.md): GuardDuty 런타임 모니터링(노드 에이전트)은 끈다(결정4). EKS 감사 로그 보호로 spec 충족.

locals {
  trail_name = "${var.name}-trail"
  # 트레일 ARN 을 미리 만든다 — 버킷 정책·키 정책이 트레일을 참조하고, 트레일은 정책이 있어야 만들어진다(순환 방지)
  trail_arn = "arn:aws:cloudtrail:${var.region}:${var.account_id}:trail/${local.trail_name}"
}

# ---------------------------------------------------------------- CloudTrail

# 트레일 전용 키. 기존 PII 키(storage)에 CloudTrail 권한을 섞지 않는다.
resource "aws_kms_key" "trail" {
  description             = "${var.name} CloudTrail logs"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # CloudTrail 은 이 트레일 것만 암호화할 수 있다
        Sid       = "CloudTrailEncrypt"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "kms:GenerateDataKey*"
        Resource  = "*"
        Condition = {
          StringEquals = { "aws:SourceArn" = local.trail_arn }
          StringLike   = { "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:aws:cloudtrail:*:${var.account_id}:trail/*" }
        }
      },
      {
        Sid       = "CloudTrailDescribe"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "kms:DescribeKey"
        Resource  = "*"
        Condition = { StringEquals = { "aws:SourceArn" = local.trail_arn } }
      },
      {
        # 로그 읽기(복호화)는 이 계정 안의 주체만 — 실제 허용은 IAM 정책이 정한다
        Sid       = "AccountDecrypt"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action    = ["kms:Decrypt", "kms:ReEncryptFrom"]
        Resource  = "*"
        Condition = {
          StringEquals = { "kms:CallerAccount" = var.account_id }
          StringLike   = { "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:aws:cloudtrail:*:${var.account_id}:trail/*" }
        }
      },
    ]
  })
}

resource "aws_kms_alias" "trail" {
  name          = "alias/${var.name}-cloudtrail"
  target_key_id = aws_kms_key.trail.key_id
}

#trivy:ignore:AVD-AWS-0089 버킷 접근 로그는 두지 않는다(로그 버킷의 로그 — 비용 대비 효용 낮음, dev)
resource "aws_s3_bucket" "trail" {
  bucket        = "${var.name}-cloudtrail-${var.account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "trail" {
  bucket = aws_s3_bucket.trail.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.trail.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration { days = var.trail_retention_days }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.trail.arn
        Condition = { StringEquals = { "aws:SourceArn" = local.trail_arn } }
      },
      {
        Sid       = "CloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.trail.arn}/AWSLogs/${var.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = local.trail_arn
          }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.trail.arn, "${aws_s3_bucket.trail.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })
}

# 다중 리전·관리 이벤트(읽기·쓰기). 데이터 이벤트(S3 객체 단위)는 비용 때문에 넣지 않는다.
# CloudWatch Logs 연동은 하지 않는다(Security Hub CloudTrail.5 지적은 dev 에서 수용, docs/D17.md).
resource "aws_cloudtrail" "this" {
  name                          = local.trail_name
  s3_bucket_name                = aws_s3_bucket.trail.id
  kms_key_id                    = aws_kms_key.trail.arn
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true

  depends_on = [aws_s3_bucket_policy.trail]
}

# ---------------------------------------------------------------- GuardDuty

resource "aws_guardduty_detector" "this" {
  enable                       = true
  finding_publishing_frequency = "FIFTEEN_MINUTES"
}

# 기능을 명시적으로 켜고 끈다 — 기본값에 맡기면 계정 상태·제공자 버전에 따라 달라진다.
locals {
  guardduty_features = {
    EKS_AUDIT_LOGS         = "ENABLED"  # spec "EKS 보호 포함"
    RDS_LOGIN_EVENTS       = "ENABLED"  # RDS PostgreSQL 비정상 로그인
    S3_DATA_EVENTS         = "ENABLED"  # 문서 버킷 이상 접근
    RUNTIME_MONITORING     = "DISABLED" # 결정4: 노드 에이전트·비용 — 끔
    EBS_MALWARE_PROTECTION = "DISABLED"
    LAMBDA_NETWORK_LOGS    = "DISABLED" # Lambda 없음
  }
}

resource "aws_guardduty_detector_feature" "this" {
  for_each    = local.guardduty_features
  detector_id = aws_guardduty_detector.this.id
  name        = each.key
  status      = each.value
}

# ---------------------------------------------------------------- Security Hub

resource "aws_securityhub_account" "this" {
  enable_default_standards  = false # 표준은 아래에서 하나만 명시적으로
  control_finding_generator = "SECURITY_CONTROL"
  auto_enable_controls      = true
}

# AWS 기초 보안 모범 사례(FSBP). GuardDuty 결과는 Security Hub 기본 통합으로 모인다.
resource "aws_securityhub_standards_subscription" "fsbp" {
  standards_arn = "arn:aws:securityhub:${var.region}::standards/aws-foundational-security-best-practices/v/1.0.0"
  depends_on    = [aws_securityhub_account.this]
}
