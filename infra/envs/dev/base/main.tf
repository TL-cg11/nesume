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
  source  = "../../../modules/logs"
  project = local.project
  env     = local.env
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
  bedrock_region        = "ap-northeast-2" # 임시 Nova 2 Lite / 이후 Haiku 5.5 모두 global 프로파일. IAM은 anthropic.+amazon. 둘 다 허용
}