resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.private_subnet_ids
}

# ingress 5432 from 클러스터 SG만. egress 없음(Terraform aws_security_group은 기본 egress를 만들지 않는다).
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "PostgreSQL from EKS nodes only"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-db" }
}

resource "aws_vpc_security_group_ingress_rule" "pg_from_eks" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = var.cluster_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# compute state와 함께 매일 새로 생기므로 최종 스냅샷 이름이 겹치지 않는다. timestamp()는 매 plan마다 diff가 난다.
resource "random_id" "snap" {
  byte_length = 4
}

# trivy 예외(dev): 매일 destroy하는 DB라 삭제 보호·백업 보존 연장은 맞지 않는다(final snapshot은 뜬다).
# IAM DB 인증은 앱이 Secrets Manager 비밀번호를 쓰므로 미사용.
#trivy:ignore:AVD-AWS-0177
#trivy:ignore:AVD-AWS-0077
#trivy:ignore:AVD-AWS-0176
resource "aws_db_instance" "this" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "nesume"
  username = "nesume"
  password = var.password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  backup_retention_period   = 1
  deletion_protection       = false
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final-${random_id.snap.hex}"
  snapshot_identifier       = var.snapshot_identifier
  apply_immediately         = true
}
