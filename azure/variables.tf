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
