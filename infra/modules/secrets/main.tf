# 시크릿 껍데기만 만든다. 값(aws_secretsmanager_secret_version)은 Terraform이 관리하지 않는다.
# 값은 base apply 뒤 put-secret-value 1회. 지우면 같은 이름을 복구 대기 7일 동안 다시 못 만든다.
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.project}/${var.env}/app"
  description             = "DB_PASSWORD, BATCH_USERNAME, BATCH_PASSWORD (JSON)"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret" "seed" {
  name                    = "${var.project}/${var.env}/seed"
  description             = "SEED_PASSWORD (JSON)"
  recovery_window_in_days = 7
}
