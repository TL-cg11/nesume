output "web_acl_arn" { value = aws_wafv2_web_acl.this.arn } # values-dev.yaml Ingress 주석에 넣는다
output "log_group" { value = aws_cloudwatch_log_group.waf.name }
output "eval_token_secret_name" { value = aws_secretsmanager_secret.eval_token.name } # 값이 아니라 이름
output "origin_token" {                                                               # edge 레이어 CloudFront 오리진 커스텀 헤더 x-origin-verify
  value     = random_password.origin_token.result
  sensitive = true
}
output "viewer_ip_header" { value = local.viewer_ip_header } # edge 레이어 CloudFront 함수가 쓰는 헤더 이름
