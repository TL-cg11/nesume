output "cluster_name" { value = module.eks.cluster_name }
output "cluster_endpoint" { value = module.eks.endpoint }
output "rds_address" { value = module.rds.address } # up.ps1 이 --set config.DB_HOST 로 넘긴다
output "rds_endpoint" { value = module.rds.endpoint }
output "nat_gateway_id" { value = aws_nat_gateway.this.id }
