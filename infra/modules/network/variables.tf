variable "name" {
  description = "리소스 이름 접두사 (nesume-dev)"
  type        = string
}
variable "region" {
  type    = string
  default = "ap-northeast-2"
}
variable "cidr" {
  type    = string
  default = "10.20.0.0/16"
}
variable "azs" {
  type    = list(string)
  default = ["ap-northeast-2a", "ap-northeast-2c"]
}
variable "public_cidrs" {
  type    = list(string)
  default = ["10.20.0.0/24", "10.20.1.0/24"]
}
variable "private_cidrs" {
  type    = list(string)
  default = ["10.20.10.0/24", "10.20.11.0/24"]
}
