#!/bin/bash
echo "Initializing local S3 bucket and SQS queue in LocalStack..."

# Create S3 Bucket
awslocal s3 mb s3://cloud-storage-bucket
awslocal s3api put-bucket-cors --bucket cloud-storage-bucket --cors-configuration '{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
      "AllowedOrigins": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}'

# Create SQS Queue
awslocal sqs create-queue --queue-name cloud-storage-tasks

echo "LocalStack AWS resources created successfully."

