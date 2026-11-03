output "vpc_id" { value = aws_vpc.this.id }
output "public_subnet_ids" { value = aws_subnet.public[*].id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "private_route_table_id" { value = aws_route_table.private.id }
output "alb_security_group_name" { value = aws_security_group.alb.name } # values-dev.yaml Ingress 주석(이름으로 찾는다)
