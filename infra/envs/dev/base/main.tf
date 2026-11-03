# dev base: 내리면 안 되는 것. compute가 terraform_remote_state로 outputs를 읽는다.
locals {
  project = "nesume"
  env     = "dev"
  name    = "${local.project}-${local.env}"
  region  = "ap-northeast-2"
}

data "aws_caller_identity" "me" {}

module "network" {
  source = "../../../modules/network"
  name   = local.name
  region = local.region
}

module "storage" {
  source     = "../../../modules/storage"
  name       = local.name
  account_id = data.aws_caller_identity.me.account_id
}

module "secrets" {
  source  = "../../../modules/secrets"
  project = local.project
  env     = local.env
}

module "logs" {
  source     = "../../../modules/logs"
  project    = local.project
  env        = local.env
  region     = local.region
  account_id = data.aws_caller_identity.me.account_id
}

module "cognito" {
  source  = "../../../modules/cognito"
  project = local.project
  env     = local.env
  region  = local.region
}

module "iam" {
  source                = "../../../modules/iam"
  name                  = local.name
  account_id            = data.aws_caller_identity.me.account_id
  region                = local.region
  docs_bucket_arn       = module.storage.bucket_arn
  kms_key_arn           = module.storage.kms_key_arn
  app_secret_arn        = module.secrets.app_secret_arn
  cognito_user_pool_arn = module.cognito.user_pool_arn
  log_group_arns        = [module.logs.app_log_group_arn, module.logs.audit_log_group_arn]
  audit_kms_key_arn     = module.logs.audit_kms_key_arn
  bedrock_region        = "ap-northeast-2" # 임시 Nova 2 Lite / 이후 Haiku 5.5 모두 global 프로파일. IAM은 anthropic.+amazon. 둘 다 허용
}

module "security" { # D17 계정 보안 서비스(CloudTrail·GuardDuty·Security Hub)
  source     = "../../../modules/security"
  name       = local.name
  account_id = data.aws_caller_identity.me.account_id
  region     = local.region
}

module "waf" { # D17 ALB 앞단 Web ACL. mode: count(관찰) → block. docs/D17.md 결정6·7절
  source     = "../../../modules/waf"
  name       = local.name
  project    = local.project
  env        = local.env
  account_id = data.aws_caller_identity.me.account_id
  region     = local.region
  mode       = "block" # 11-03 Count 관찰 뒤 전환(7절). 문제 시 "count" 로 되돌린다
}
