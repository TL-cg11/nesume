output "region" { value = local.region }
output "account_id" { value = data.aws_caller_identity.me.account_id }

output "vpc_id" { value = module.network.vpc_id }
output "public_subnet_ids" { value = module.network.public_subnet_ids }
output "private_subnet_ids" { value = module.network.private_subnet_ids }
output "private_route_table_id" { value = module.network.private_route_table_id }

output "docs_bucket" { value = module.storage.bucket }
output "kms_key_arn" { value = module.storage.kms_key_arn }
output "kms_alias" { value = module.storage.kms_alias }

output "app_secret_arn" { value = module.secrets.app_secret_arn }
output "app_secret_name" { value = module.secrets.app_secret_name }
output "seed_secret_arn" { value = module.secrets.seed_secret_arn }

output "app_log_group" { value = module.logs.app_log_group }
output "audit_log_group" { value = module.logs.audit_log_group }
output "audit_kms_key_arn" { value = module.logs.audit_kms_key_arn }

output "ci_role_arn" { value = module.iam.ci_role_arn }
output "eks_cluster_role_arn" { value = module.iam.eks_cluster_role_arn }
output "eks_node_role_arn" { value = module.iam.eks_node_role_arn }
output "app_role_arn" { value = module.iam.app_role_arn }
output "batch_role_arn" { value = module.iam.batch_role_arn }
output "alb_controller_role_arn" { value = module.iam.alb_controller_role_arn }
output "external_secrets_role_arn" { value = module.iam.external_secrets_role_arn }
output "fluent_bit_role_arn" { value = module.iam.fluent_bit_role_arn }             # D14
output "cloudwatch_agent_role_arn" { value = module.iam.cloudwatch_agent_role_arn } # D14

output "cognito_user_pool_id" { value = module.cognito.user_pool_id }
output "cognito_client_ids" { value = module.cognito.client_ids }
output "cognito_issuer" { value = module.cognito.issuer }
output "cognito_jwks_url" { value = module.cognito.jwks_url }
output "cloudtrail_arn" { value = module.security.trail_arn }                    # D17
output "cloudtrail_bucket" { value = module.security.trail_bucket }              # D17
output "guardduty_detector_id" { value = module.security.guardduty_detector_id } # D17
output "waf_web_acl_arn" { value = module.waf.web_acl_arn }                      # D17 → values-dev.yaml Ingress 주석
output "waf_log_group" { value = module.waf.log_group }                          # D17
output "eval_waf_token_secret" { value = module.waf.eval_token_secret_name }     # D17 평가 러너가 읽는 시크릿 이름
