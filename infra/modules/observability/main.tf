# D14 로그·모니터링 (compute 레이어. 클러스터와 함께 올라가고 내려간다. 로그 그룹·역할은 base).
#
#  1. Fluent Bit(aws-for-fluent-bit) DaemonSet: 파드 stdout(JSON, core/logging.py) → CloudWatch Logs
#     - log_type == "audit" 인 줄 → /nesume/<env>/audit (보존 90일·KMS), 나머지 → /nesume/<env>/app (30일)
#     - 스트림 이름 = <namespace>.<pod>. request_id 로 한 요청의 로그를 두 그룹에서 모두 찾을 수 있다.
#  2. Container Insights: amazon-cloudwatch-observability 애드온(cloudwatch-agent 만. 컨테이너 로그 수집은 1번이 하므로 끈다)
#  3. 메트릭 필터(네임스페이스 nesume/<env>): 요청 수·5xx·duration_ms·차단 수. is_test 트래픽은 전부 제외.
#  4. 알람 → SNS nesume-<env>-alerts (이메일 선택. Slack·자동 차단 구독은 D16)
#  5. CloudWatch 대시보드 + Logs Insights 저장 쿼리(docs/ops/observability.md 와 같은 내용)

locals {
  ns   = "${var.project}/${var.env}"
  name = "${var.project}-${var.env}"
  # 접근 로그 1줄(request_id.py http_request). 평가 러너(is_test=true)는 지표에서 뺀다.
  not_test   = "($.is_test NOT EXISTS || $.is_test IS FALSE)"
  access_log = "{ $.msg = \"http_request\" && ${local.not_test} }"
}

# ---------- 1. Fluent Bit ----------
resource "aws_eks_pod_identity_association" "fluent_bit" {
  cluster_name    = var.cluster_name
  namespace       = var.fluent_bit_namespace
  service_account = "aws-for-fluent-bit"
  role_arn        = var.fluent_bit_role_arn
}

resource "helm_release" "fluent_bit" {
  name             = "aws-for-fluent-bit"
  namespace        = var.fluent_bit_namespace
  create_namespace = true
  repository       = "https://aws.github.io/eks-charts"
  chart            = "aws-for-fluent-bit"
  version          = var.fluent_bit_chart_version
  timeout          = 600

  values = [yamlencode({
    serviceAccount = { create = true, name = "aws-for-fluent-bit" } # Pod Identity 연결과 같은 이름
    # 임베딩 전용 노드(taint)에도 올라가야 그 파드 로그가 온다
    tolerations = [{ operator = "Exists" }]
    resources = {
      requests = { cpu = "50m", memory = "64Mi" }
      limits   = { cpu = "200m", memory = "200Mi" }
    }
    # containerd(CRI) 로그 형식. 앱 JSON 은 kubernetes 필터 Merge_Log 가 풀어 최상위 필드로 만든다.
    input = {
      enabled         = true
      tag             = "kube.*"
      path            = "/var/log/containers/*.log"
      db              = "/var/log/flb_kube.db"
      multilineParser = "cri"
      memBufLimit     = "20MB"
      skipLongLines   = "On"
    }
    filter = {
      enabled           = true
      match             = "kube.*"
      mergeLog          = "On"
      mergeLogKey       = ""
      keepLog           = "Off"
      k8sLoggingParser  = "On"
      k8sLoggingExclude = "On"
      # 라벨·주석은 줄마다 붙어 비용만 든다
      extraFilters = <<-EOT
        Labels          Off
        Annotations     Off
      EOT
    }
    # log_type=audit 줄만 태그를 바꿔 감사 그룹으로 보낸다(core/logging.py log_type_of)
    additionalFilters = <<-EOT
      [FILTER]
          Name          rewrite_tag
          Match         kube.*
          Rule          $log_type ^audit$ audit.$TAG false
          Emitter_Name  re_audit
          Emitter_Mem_Buf_Limit 10M
    EOT
    cloudWatchLogs    = { enabled = false } # 기본 출력 대신 아래 두 출력을 쓴다
    additionalOutputs = <<-EOT
      [OUTPUT]
          Name                cloudwatch_logs
          Match               kube.*
          region              ${var.region}
          log_group_name      ${var.app_log_group}
          log_stream_template $kubernetes['namespace_name'].$kubernetes['pod_name']
          log_stream_prefix   unknown.
          auto_create_group   false
          retry_limit         2

      [OUTPUT]
          Name                cloudwatch_logs
          Match               audit.*
          region              ${var.region}
          log_group_name      ${var.audit_log_group}
          log_stream_template $kubernetes['namespace_name'].$kubernetes['pod_name']
          log_stream_prefix   unknown.
          auto_create_group   false
          retry_limit         2
    EOT
  })]

  depends_on = [aws_eks_pod_identity_association.fluent_bit]
}

# ---------- 2. Container Insights ----------
resource "aws_eks_addon" "cloudwatch_observability" {
  cluster_name                = var.cluster_name
  addon_name                  = "amazon-cloudwatch-observability"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
  # 컨테이너 로그는 Fluent Bit(1번)가 보낸다. 애드온의 Fluent Bit 는 끈다(이중 전송 방지).
  configuration_values = jsonencode({
    containerLogs = { enabled = false }
    agent = {
      config = {
        logs = { metrics_collected = { kubernetes = { enhanced_container_insights = true } } }
      }
    }
  })
  pod_identity_association {
    role_arn        = var.cloudwatch_agent_role_arn
    service_account = "cloudwatch-agent"
  }
}

# ---------- 3. 메트릭 필터 (app 로그 그룹) ----------
resource "aws_cloudwatch_log_metric_filter" "requests" {
  name           = "${local.name}-requests"
  log_group_name = var.app_log_group
  pattern        = local.access_log
  metric_transformation {
    name          = "RequestCount"
    namespace     = local.ns
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "errors_5xx" {
  name           = "${local.name}-5xx"
  log_group_name = var.app_log_group
  pattern        = "{ $.msg = \"http_request\" && $.status >= 500 && ${local.not_test} }"
  metric_transformation {
    name          = "Error5xxCount"
    namespace     = local.ns
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "duration" {
  name           = "${local.name}-duration"
  log_group_name = var.app_log_group
  pattern        = local.access_log
  metric_transformation {
    name      = "DurationMs"
    namespace = local.ns
    value     = "$.duration_ms"
    unit      = "Milliseconds"
  }
}

# 차단 수. 감사 그룹의 log_type=audit 줄 중 decision=block. (B11 기록 함수가 nesume.audit 로거로 1줄 남기면 채워진다.
# 그 전까지는 0 → 알람은 울리지 않고, 화면의 차단 현황은 DB 집계(/admin/dashboard/summary)가 기준.)
resource "aws_cloudwatch_log_metric_filter" "blocks" {
  name           = "${local.name}-blocks"
  log_group_name = var.audit_log_group
  pattern        = "{ $.decision = \"block\" && ${local.not_test} }"
  metric_transformation {
    name          = "BlockCount"
    namespace     = local.ns
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "canary" {
  name           = "${local.name}-canary"
  log_group_name = var.audit_log_group
  pattern        = "{ $.canary_hit IS TRUE && ${local.not_test} }"
  metric_transformation {
    name          = "CanaryHitCount"
    namespace     = local.ns
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

# ---------- 4. SNS + 알람 ----------
#trivy:ignore:AVD-AWS-0095 # 알람 본문에 비밀 없음. KMS 를 붙이면 CloudWatch→SNS 게시에 키 정책이 더 필요하다(D16 에서 Slack 구독과 함께)
resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# 5xx 비율 > N% (5분). 요청이 없으면 평가하지 않는다.
resource "aws_cloudwatch_metric_alarm" "error_rate" {
  alarm_name          = "${local.name}-5xx-rate"
  alarm_description   = "5xx 비율이 ${var.error_rate_threshold_percent}% 를 넘음(5분, is_test 제외). Logs Insights '5xx 요청' 쿼리로 request_id 확인"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.error_rate_threshold_percent
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  metric_query {
    id          = "rate"
    expression  = "IF(req > 0, 100 * err / req, 0)"
    label       = "5xx %"
    return_data = true
  }
  metric_query {
    id = "req"
    metric {
      namespace   = local.ns
      metric_name = "RequestCount"
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id = "err"
    metric {
      namespace   = local.ns
      metric_name = "Error5xxCount"
      period      = 300
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "p95" {
  alarm_name          = "${local.name}-p95-latency"
  alarm_description   = "요청 p95 지연이 ${var.p95_threshold_ms}ms 를 넘음(5분, is_test 제외)"
  namespace           = local.ns
  metric_name         = "DurationMs"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.p95_threshold_ms
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# 차단 급증: 직전 추세 대비 3배(표준편차 밴드). 기준선은 CloudWatch 가 2주 데이터로 학습한다.
resource "aws_cloudwatch_metric_alarm" "block_surge" {
  alarm_name          = "${local.name}-block-surge"
  alarm_description   = "가드레일 차단 수가 기준선 밴드(3배)를 넘음(15분). 운영 대시보드에서 상위 사용자 확인 → D16 세션 차단"
  comparison_operator = "GreaterThanUpperThreshold"
  evaluation_periods  = 1
  threshold_metric_id = "band"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  metric_query {
    id          = "band"
    expression  = "ANOMALY_DETECTION_BAND(blocks, 3)"
    label       = "BlockCount 기준선"
    return_data = true
  }
  metric_query {
    id          = "blocks"
    return_data = true
    metric {
      namespace   = local.ns
      metric_name = "BlockCount"
      period      = 900
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "canary" {
  alarm_name          = "${local.name}-canary-hit"
  alarm_description   = "카나리 문서가 응답에 섞임(유출 시도). 즉시 운영 대시보드 → 최근 이벤트의 사용자 확인"
  namespace           = local.ns
  metric_name         = "CanaryHitCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

# Container Insights
resource "aws_cloudwatch_metric_alarm" "pod_restarts" {
  alarm_name          = "${local.name}-pod-restarts"
  alarm_description   = "5분 동안 컨테이너 재시작이 ${var.pod_restart_threshold}회 이상(스팟 회수 1~2회는 정상)"
  namespace           = "ContainerInsights"
  metric_name         = "pod_number_of_container_restarts"
  dimensions          = { ClusterName = var.cluster_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.pod_restart_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "node_cpu" {
  alarm_name          = "${local.name}-node-cpu"
  alarm_description   = "노드 CPU 사용률 85% 초과(10분)"
  namespace           = "ContainerInsights"
  metric_name         = "node_cpu_utilization"
  dimensions          = { ClusterName = var.cluster_name }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "node_memory" {
  alarm_name          = "${local.name}-node-memory"
  alarm_description   = "노드 메모리 사용률 85% 초과(10분). t4g.medium 4GB, 임베더 노드 ~3GB 사용이 정상"
  namespace           = "ContainerInsights"
  metric_name         = "node_memory_utilization"
  dimensions          = { ClusterName = var.cluster_name }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# RDS
resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${local.name}-rds-connections"
  alarm_description   = "RDS 연결 수 ${var.rds_connections_threshold} 초과(db.t4g.micro 상한 ~80). 앱 레플리카·풀 크기 확인"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  dimensions          = { DBInstanceIdentifier = var.rds_identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.rds_connections_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${local.name}-rds-free-storage"
  alarm_description   = "RDS 여유 스토리지 2GB 미만"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = var.rds_identifier }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "LessThanThreshold"
  threshold           = var.rds_free_storage_bytes
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

# ---------- 5. 대시보드 + Logs Insights 저장 쿼리 ----------
locals {
  w = { h = 6, w = 8 }
  dashboard = {
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 8, height = 6
        properties = {
          title   = "요청 수 (is_test 제외)", region = var.region, stat = "Sum", period = 300, view = "timeSeries"
          metrics = [[local.ns, "RequestCount", { label = "요청" }], [local.ns, "Error5xxCount", { label = "5xx", color = "#d13212" }]]
        }
      },
      {
        type = "metric", x = 8, y = 0, width = 8, height = 6
        properties = {
          title = "5xx 비율 %", region = var.region, period = 300, view = "timeSeries"
          metrics = [
            [{ expression = "IF(req > 0, 100 * err / req, 0)", label = "5xx %", id = "rate", color = "#d13212" }],
            [local.ns, "RequestCount", { id = "req", visible = false, stat = "Sum" }],
            [local.ns, "Error5xxCount", { id = "err", visible = false, stat = "Sum" }],
          ]
          annotations = { horizontal = [{ value = var.error_rate_threshold_percent, label = "알람" }] }
        }
      },
      {
        type = "metric", x = 16, y = 0, width = 8, height = 6
        properties = {
          title       = "지연 ms", region = var.region, period = 300, view = "timeSeries"
          metrics     = [[local.ns, "DurationMs", { stat = "p50", label = "p50" }], [local.ns, "DurationMs", { stat = "p95", label = "p95" }], [local.ns, "DurationMs", { stat = "p99", label = "p99" }]]
          annotations = { horizontal = [{ value = var.p95_threshold_ms, label = "p95 알람" }] }
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 8, height = 6
        properties = {
          title   = "가드레일 차단·카나리 (is_test 제외)", region = var.region, stat = "Sum", period = 900, view = "timeSeries"
          metrics = [[local.ns, "BlockCount", { label = "차단", color = "#d13212" }], [local.ns, "CanaryHitCount", { label = "카나리", color = "#8c4fff" }]]
        }
      },
      {
        type = "metric", x = 8, y = 6, width = 8, height = 6
        properties = {
          title = "노드 CPU·메모리 %", region = var.region, stat = "Average", period = 300, view = "timeSeries"
          metrics = [
            ["ContainerInsights", "node_cpu_utilization", "ClusterName", var.cluster_name, { label = "CPU" }],
            ["ContainerInsights", "node_memory_utilization", "ClusterName", var.cluster_name, { label = "메모리" }],
          ]
          yAxis = { left = { min = 0, max = 100 } }
        }
      },
      {
        type = "metric", x = 16, y = 6, width = 8, height = 6
        properties = {
          title = "파드 재시작 · 실행 중 파드", region = var.region, period = 300, view = "timeSeries"
          metrics = [
            ["ContainerInsights", "pod_number_of_container_restarts", "ClusterName", var.cluster_name, { stat = "Sum", label = "재시작" }],
            ["ContainerInsights", "namespace_number_of_running_pods", "ClusterName", var.cluster_name, "Namespace", "dev", { stat = "Average", label = "dev 파드" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 8, height = 6
        properties = {
          title = "RDS 연결 · CPU", region = var.region, stat = "Average", period = 300, view = "timeSeries"
          metrics = [
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.rds_identifier, { label = "연결" }],
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.rds_identifier, { label = "CPU %", yAxis = "right" }],
          ]
        }
      },
      {
        type = "log", x = 8, y = 12, width = 16, height = 6
        properties = {
          title = "최근 5xx (request_id 로 추적)", region = var.region, view = "table"
          query = "SOURCE '${var.app_log_group}' | fields @timestamp, request_id, method, path, status, duration_ms, user_id | filter msg = \"http_request\" and status >= 500 and (isblank(is_test) or is_test = 0) | sort @timestamp desc | limit 20"
        }
      },
      {
        type = "log", x = 0, y = 18, width = 12, height = 6
        properties = {
          title = "배치(CronJob) 결과 — jobs_collector · purge", region = var.region, view = "table"
          query = "SOURCE '${var.app_log_group}' | fields @timestamp, kubernetes.pod_name, level, msg | filter kubernetes.pod_name like /jobs-collector|purge/ and level in [\"INFO\",\"ERROR\"] and msg like /done|failed|error|collected/ | sort @timestamp desc | limit 20"
        }
      },
      {
        type = "log", x = 12, y = 18, width = 12, height = 6
        properties = {
          title = "감사 로그 — 최근 운영자 조치(역할 변경 등)", region = var.region, view = "table"
          query = "SOURCE '${var.audit_log_group}' | fields @timestamp, msg, user_id, from, to, actor, request_id | sort @timestamp desc | limit 20"
        }
      },
    ]
  }
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name
  dashboard_body = jsonencode(local.dashboard)
}

# 자주 쓰는 Logs Insights 쿼리(콘솔 Logs Insights → 저장된 쿼리). 같은 쿼리를 docs/ops/observability.md 에 둔다.
resource "aws_cloudwatch_query_definition" "trace_request" {
  name            = "${local.name}/요청 추적 (request_id)"
  log_group_names = [var.app_log_group, var.audit_log_group]
  query_string    = <<-EOT
    fields @timestamp, @logStream, level, logger, msg, status, duration_ms, user_id, role
    | filter request_id = "REQUEST_ID_HERE"
    | sort @timestamp asc
  EOT
}

resource "aws_cloudwatch_query_definition" "errors_5xx" {
  name            = "${local.name}/5xx 요청"
  log_group_names = [var.app_log_group]
  query_string    = <<-EOT
    fields @timestamp, request_id, method, path, status, duration_ms, user_id, role
    | filter msg = "http_request" and status >= 500 and (isblank(is_test) or is_test = 0)
    | sort @timestamp desc
    | limit 100
  EOT
}

resource "aws_cloudwatch_query_definition" "slow_routes" {
  name            = "${local.name}/느린 라우트 p95"
  log_group_names = [var.app_log_group]
  query_string    = <<-EOT
    filter msg = "http_request" and (isblank(is_test) or is_test = 0)
    | stats count() as requests, pct(duration_ms, 95) as p95_ms, avg(duration_ms) as avg_ms by method, path
    | sort p95_ms desc
    | limit 30
  EOT
}

resource "aws_cloudwatch_query_definition" "blocks_by_user" {
  name            = "${local.name}/사용자별 차단"
  log_group_names = [var.audit_log_group]
  query_string    = <<-EOT
    filter decision = "block" and (isblank(is_test) or is_test = 0)
    | stats count() as blocks, count_distinct(request_id) as requests by user_id, role
    | sort blocks desc
    | limit 20
  EOT
}

resource "aws_cloudwatch_query_definition" "exceptions" {
  name            = "${local.name}/예외 스택"
  log_group_names = [var.app_log_group]
  query_string    = <<-EOT
    fields @timestamp, request_id, logger, msg, exc
    | filter level = "ERROR" or ispresent(exc)
    | sort @timestamp desc
    | limit 50
  EOT
}
