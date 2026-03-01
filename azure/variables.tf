variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "northeurope"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "badi-oerlikon"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
  
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "aci_storage_account_name" {
  description = "Name of the ACI storage account holding Table Storage occupancy data (managed by azure/collector-aci/)"
  type        = string
  default     = "badiacidevyb1a"
}

variable "aci_resource_group_name" {
  description = "Resource group of the ACI storage account"
  type        = string
  default     = "badi-oerlikon-dev-aci-rg"
}
