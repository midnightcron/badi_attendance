variable "location" {
  description = "Azure region"
  type        = string
  default     = "westeurope"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "badi-oerlikon"
}

variable "environment" {
  description = "Environment name"
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

variable "websocket_url" {
  description = "CrowdMonitor WebSocket URL"
  type        = string
  default     = "wss://badi-public.crowdmonitor.ch:9591/api"
}

variable "target_uid" {
  description = "CrowdMonitor UID to track"
  type        = string
  default     = "SSD-7"
}
