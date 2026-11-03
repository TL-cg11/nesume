variable "name" { type = string } # nesume-dev
variable "cluster_version" {
  type    = string
  default = "1.36" # 표준 지원 2027-08-02까지. 연장 지원 버전은 시간당 0.60달러
}
variable "cluster_role_arn" { type = string }
variable "node_role_arn" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }
variable "ci_role_arn" { type = string }
variable "team_user_arns" {
  description = "팀원 IAM 사용자 ARN. View(클러스터) + Edit(dev 네임스페이스)"
  type        = list(string)
}
variable "pod_identities" {
  description = "Pod Identity 연결. key = 이름, value = { namespace, service_account, role_arn }"
  type        = map(object({ namespace = string, service_account = string, role_arn = string }))
}

# ---------- D20 임베딩 노드그룹 ----------
variable "embedding_node_enabled" {
  description = "bge-m3 embedder 전용 노드그룹(1대) 생성 여부. false 면 차트의 embedder.enabled 도 false 로"
  type        = bool
  default     = true
}
variable "embedding_instance_types" {
  description = "임베딩 노드 타입. 전부 arm64 8GB 이상(fp32 모델 RSS ~3GB). 여러 개를 두어 용량 부족 시 ASG 가 고른다"
  type        = list(string)
  default     = ["m7g.large", "m6g.large", "t4g.large"]
}
variable "embedding_capacity_type" {
  description = "ON_DEMAND(기본, 회수 없음) 또는 SPOT(1/3 비용, 회수 시 임베딩 1~2분 중단)"
  type        = string
  default     = "ON_DEMAND"
  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], var.embedding_capacity_type)
    error_message = "embedding_capacity_type must be ON_DEMAND or SPOT."
  }
}
