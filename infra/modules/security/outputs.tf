output "trail_arn" { value = aws_cloudtrail.this.arn }
output "trail_bucket" { value = aws_s3_bucket.trail.bucket }
output "guardduty_detector_id" { value = aws_guardduty_detector.this.id }
output "config_bucket" { value = try(aws_s3_bucket.config[0].bucket, null) }
