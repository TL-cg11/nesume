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
