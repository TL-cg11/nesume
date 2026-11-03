alb_controller_chart_version   = "3.6.2"  # helm search repo eks/aws-load-balancer-controller (2026-10-26)
external_secrets_chart_version = "2.14.0" # helm search repo external-secrets/external-secrets (2026-10-26)
fluent_bit_chart_version       = "0.2.0"  # helm search repo eks/aws-for-fluent-bit (D14, 2026-11-02. Fluent Bit 3.2.1)
# D16 Discord 웹훅 Lambda. 2026-11-03 apply 된 상태. 기본값(false)이면 infra 워크플로·동료 apply 가 알림 Lambda 등 5개를
# destroy 하므로 tfvars 에 고정한다(-var 로 넘길 필요 없음). 시크릿 nesume/dev/app 의 ALERTS_WEBHOOK_URL 이 전제.
webhook_alerts_enabled = true
