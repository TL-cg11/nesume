output "cluster_name" { value = aws_eks_cluster.this.name }
output "endpoint" { value = aws_eks_cluster.this.endpoint }
output "ca" { value = aws_eks_cluster.this.certificate_authority[0].data }
output "cluster_security_group_id" { value = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id }
output "node_group_id" { value = aws_eks_node_group.default.id }                     # addons의 선행 조건으로 쓴다
output "embedding_node_group_id" { value = one(aws_eks_node_group.embedding[*].id) } # D20. 비활성이면 null
