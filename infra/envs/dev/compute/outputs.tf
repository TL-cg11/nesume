output "cluster_name" { value = module.eks.cluster_name }
output "cluster_endpoint" { value = module.eks.endpoint }
output "rds_address" { value = module.rds.address } # up.ps1 이 --set config.DB_HOST 로 넘긴다
output "rds_endpoint" { value = module.rds.endpoint }
output "nat_gateway_id" { value = aws_nat_gateway.this.id }
output "alerts_topic_arn" { value = module.observability.alerts_topic_arn }   # D14 → D16 이 구독
output "cloudwatch_dashboard" { value = module.observability.dashboard_name } # D14
