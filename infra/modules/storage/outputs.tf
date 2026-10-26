output "bucket" { value = aws_s3_bucket.docs.bucket }
output "bucket_arn" { value = aws_s3_bucket.docs.arn }
output "kms_key_arn" { value = aws_kms_key.pii.arn }
output "kms_alias" { value = aws_kms_alias.pii.name }   # alias/nesume-dev-pii
