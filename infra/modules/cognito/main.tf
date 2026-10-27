# Cognito user pool (D6). 역할은 그룹(cognito:groups)으로 전달한다. 클레임 계약은 docs/D-deliverables/roles-grades.md 8장.
# 환경 디렉터리(infra/envs/<env>)에서 모듈로 호출한다(D8). apply는 AWS 크레딧 뒤.
# 그 전에는 init -backend=false / validate / fmt -check 까지만 확인한다.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

locals {
  name = "${var.project}-${var.env}"
  # 역할 그룹 3개 + 테스트 플래그 그룹 1개. 그룹이 없으면 user.
  groups = ["mentor", "operator", "system", "test"]
}

resource "aws_cognito_user_pool" "this" {
  name                     = local.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # 운영자 TOTP 강제는 백엔드(D7)가 AdminGetUser 로 확인한다. 풀 설정은 OPTIONAL.
  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length    = 10
    require_uppercase = true
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # ENFORCED(탈취 자격 증명 차단)는 Plus 티어 비용 확인 뒤(v1 메모).
  user_pool_add_ons {
    advanced_security_mode = "AUDIT"
  }

  deletion_protection = var.env == "prod" ? "ACTIVE" : "INACTIVE"

  tags = {
    Project = var.project
    Env     = var.env
  }
}

resource "aws_cognito_user_group" "role" {
  for_each     = toset(local.groups)
  name         = each.key
  user_pool_id = aws_cognito_user_pool.this.id
  description  = each.key == "test" ? "test flag (not a role)" : "role group"
}

# 웹 클라이언트: SRP 만. USER_PASSWORD_AUTH 는 웹에 열지 않는다.
resource "aws_cognito_user_pool_client" "web" {
  name                          = "web"
  user_pool_id                  = aws_cognito_user_pool.this.id
  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_SRP_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 14
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  refresh_token_rotation {
    feature                    = "ENABLED"
    retry_grace_period_seconds = 30
  }
}

# 러너·배치·시드 검증용 클라이언트: USER_PASSWORD_AUTH. 백엔드는 COGNITO_CLIENT_IDS 로 두 클라이언트를 모두 허용한다(D7).
resource "aws_cognito_user_pool_client" "runner" {
  name                          = "runner"
  user_pool_id                  = aws_cognito_user_pool.this.id
  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 14
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  refresh_token_rotation {
    feature                    = "ENABLED"
    retry_grace_period_seconds = 30
  }
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = local.name
  user_pool_id = aws_cognito_user_pool.this.id
}
