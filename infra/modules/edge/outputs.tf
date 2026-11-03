output "domain_name" { value = aws_cloudfront_distribution.this.domain_name } # 배포를 지우지 않는 한 고정
output "url" { value = "https://${aws_cloudfront_distribution.this.domain_name}" }
output "distribution_id" { value = aws_cloudfront_distribution.this.id }
