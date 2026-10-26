# D14 Fluent Bit가 쓴다. 앱 로그와 감사 로그 분리.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project}/${var.env}/app"
  retention_in_days = var.retention_in_days
}

resource "aws_cloudwatch_log_group" "audit" {
  name              = "/${var.project}/${var.env}/audit"
  retention_in_days = var.retention_in_days
}
