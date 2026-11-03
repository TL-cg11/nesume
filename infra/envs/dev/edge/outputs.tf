output "url" { value = module.edge.url } # 팀 공지 주소. 배포를 지우지 않는 한 고정
output "domain_name" { value = module.edge.domain_name }
output "distribution_id" { value = module.edge.distribution_id }
output "origin_domain" { value = data.aws_lb.ingress.dns_name }
