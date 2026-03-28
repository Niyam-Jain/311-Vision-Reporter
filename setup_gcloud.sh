#!/bin/bash
# Google Cloud setup for 311 Vision Reporter
# Run these commands after setting up your GCP project

echo "=== Step 1: Set your project ==="
echo "Run: gcloud config set project YOUR_PROJECT_ID"

echo ""
echo "=== Step 2: Enable required APIs ==="
gcloud services enable aiplatform.googleapis.com
gcloud services enable geocoding-backend.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com

echo ""
echo "=== Step 3: Authenticate ==="
echo "Run: gcloud auth application-default login"

echo ""
echo "=== Step 4: Create .env file ==="
echo "Copy .env.example to .env and fill in your values"

echo ""
echo "Done! All APIs enabled."
