#!/bin/bash
# Build and load Docker image to kind cluster

set -e

echo "Building operator Docker image..."
docker build -t self-healing-operator:latest .

echo "Loading image into kind cluster..."
kind load docker-image self-healing-operator:latest

echo "Image loaded successfully!"
echo "Update the deployment or values.yaml to use: self-healing-operator:latest"
