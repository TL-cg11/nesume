variable "cluster_name" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "alb_controller_chart_version" { type = string }   # helm search repo eks/aws-load-balancer-controller
variable "external_secrets_chart_version" { type = string } # helm search repo external-secrets/external-secrets
