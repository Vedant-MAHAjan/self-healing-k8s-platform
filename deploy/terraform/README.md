# Self-Healing Kubernetes Platform - Terraform Infrastructure

This directory contains Terraform configurations for deploying the self-healing Kubernetes platform infrastructure.

## Supported Providers

- **AWS EKS** - Amazon Elastic Kubernetes Service
- **GCP GKE** - Google Kubernetes Engine  
- **Azure AKS** - Azure Kubernetes Service

## Directory Structure

```
terraform/
├── aws/          # AWS EKS cluster setup
├── gcp/          # GCP GKE cluster setup
├── azure/        # Azure AKS cluster setup
└── modules/      # Shared Terraform modules
```

## Quick Start

### AWS EKS

```bash
cd aws
terraform init
terraform plan
terraform apply
```

### Configure kubectl

```bash
# AWS
aws eks update-kubeconfig --name self-healing-cluster --region us-west-2

# GCP
gcloud container clusters get-credentials self-healing-cluster --region us-central1

# Azure
az aks get-credentials --resource-group self-healing-rg --name self-healing-cluster
```

## Variables

See individual provider directories for specific variables.

Common variables:
- `cluster_name` - Name of the Kubernetes cluster
- `region` - Cloud provider region
- `node_count` - Number of worker nodes
- `node_instance_type` - Instance type for worker nodes
- `enable_prometheus` - Install Prometheus Operator
- `enable_argocd` - Install ArgoCD

## Outputs

- `cluster_endpoint` - Kubernetes cluster API endpoint
- `cluster_name` - Name of the created cluster
- `kubeconfig_command` - Command to configure kubectl
