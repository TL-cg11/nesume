output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  value = aws_cognito_user_pool.this.arn
}

output "issuer" {
  description = "COGNITO_ISSUER"
  value       = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}

output "jwks_url" {
  description = "COGNITO_JWKS_URL"
  value       = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.this.id}/.well-known/jwks.json"
}

output "client_ids" {
  description = "COGNITO_CLIENT_IDS = join(\",\", values(client_ids))"
  value = {
    web    = aws_cognito_user_pool_client.web.id
    runner = aws_cognito_user_pool_client.runner.id
  }
}

output "domain" {
  value = aws_cognito_user_pool_domain.this.domain
}
