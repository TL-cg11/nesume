#!/bin/bash
# LocalStack ready.d 훅: 기동 완료 후 실행된다.
# 무료 플랜은 재시작 시 리소스가 초기화되므로 매 기동마다 실행되며, 멱등하게 작성한다.
set -euo pipefail

: "${S3_BUCKET_NAME:?}" "${KMS_KEY_ALIAS:?}" "${APP_SECRET_NAME:?}" "${AWS_DEFAULT_REGION:?}"

# S3: 비공개 버킷 + 퍼블릭 액세스 차단 + 기본 암호화(KMS)
if ! awslocal s3api head-bucket --bucket "$S3_BUCKET_NAME" 2>/dev/null; then
  if [ "$AWS_DEFAULT_REGION" = "us-east-1" ]; then
    awslocal s3api create-bucket --bucket "$S3_BUCKET_NAME"
  else
    awslocal s3api create-bucket --bucket "$S3_BUCKET_NAME" \
      --create-bucket-configuration LocationConstraint="$AWS_DEFAULT_REGION"
  fi
fi
awslocal s3api put-public-access-block --bucket "$S3_BUCKET_NAME" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# KMS: 개인정보 컬럼/S3 암호화용 키(alias로 참조)
if ! awslocal kms describe-key --key-id "$KMS_KEY_ALIAS" >/dev/null 2>&1; then
  KEY_ID=$(awslocal kms create-key --description "local pii key" --query KeyMetadata.KeyId --output text)
  awslocal kms create-alias --alias-name "$KMS_KEY_ALIAS" --target-key-id "$KEY_ID"
fi
awslocal s3api put-bucket-encryption --bucket "$S3_BUCKET_NAME" \
  --server-side-encryption-configuration "{\"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"aws:kms\",\"KMSMasterKeyID\":\"$KMS_KEY_ALIAS\"}}]}"

# Secrets Manager: 앱 비밀정보 자리(값은 각자 put-secret-value로 갱신)
if ! awslocal secretsmanager describe-secret --secret-id "$APP_SECRET_NAME" >/dev/null 2>&1; then
  awslocal secretsmanager create-secret --name "$APP_SECRET_NAME" \
    --kms-key-id "$KMS_KEY_ALIAS" --secret-string '{}'
fi

echo "[init] s3=$S3_BUCKET_NAME kms=$KMS_KEY_ALIAS secret=$APP_SECRET_NAME ready"
