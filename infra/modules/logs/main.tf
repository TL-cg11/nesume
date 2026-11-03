# D14 Fluent Bit(infra/modules/observability)가 쓴다. 앱 로그와 감사 로그 분리.
#   /<project>/<env>/app    log_type=app   보존 30일
#   /<project>/<env>/audit  log_type=audit 보존 90일(spec 10.2 로그 보관 90일), KMS 암호화
# base 레이어에 두는 이유: compute 를 내려도 로그는 남아야 한다.
# trivy 예외: 앱 로그 그룹은 KMS 없이 둔다(PII 를 넣지 않는 규칙, core/logging.py). 감사 그룹만 CMK.

#trivy:ignore:AVD-AWS-0017
resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project}/${var.env}/app"
  retention_in_days = var.app_retention_in_days
}

resource "aws_cloudwatch_log_group" "audit" {
  name              = "/${var.project}/${var.env}/audit"
  retention_in_days = var.audit_retention_in_days
  kms_key_id        = aws_kms_key.audit.arn
}

# 감사 로그 그룹 전용 키. CloudWatch Logs 서비스가 이 계정·리전의 로그 그룹에서만 쓸 수 있게 암호화 컨텍스트로 제한한다.
resource "aws_kms_key" "audit" {
  description             = "${var.project}-${var.env} audit log group"
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
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.region}.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.region}:${var.account_id}:log-group:/${var.project}/${var.env}/audit"
          }
        }
      },
    ]
  })
}

resource "aws_kms_alias" "audit" {
  name          = "alias/${var.project}-${var.env}-audit-logs"
  target_key_id = aws_kms_key.audit.key_id
}
