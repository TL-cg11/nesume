variable "name" { type = string } # nesume-dev
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "cluster_security_group_id" { type = string } # 노드가 쓰는 EKS 클러스터 SG
variable "password" {
  type      = string
  sensitive = true
}
variable "snapshot_identifier" {
  description = "복원할 스냅샷. 기본 null = 빈 DB"
  type        = string
  default     = null
}
