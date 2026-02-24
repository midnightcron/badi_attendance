terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

provider "random" {
}

# Generate unique but stable suffix for storage accounts
resource "random_string" "storage_suffix" {
  length  = 4
  special = false
  upper   = false
  keepers = {
    project_name = var.project_name
    environment  = var.environment
  }
}

# Local variables
locals {
  project_name          = var.project_name
  environment           = var.environment
  storage_account_name  = replace("badisa${random_string.storage_suffix.result}", "-", "")
  function_storage_name = replace("badfuncsa${random_string.storage_suffix.result}", "-", "")
}

# Resource Group
resource "azurerm_resource_group" "rg" {
  name     = "${local.project_name}-${local.environment}-rg"
  location = var.location
}

# Storage Account for blob storage (data)
resource "azurerm_storage_account" "storage" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  access_tier              = "Hot"
}

# Blob Container for occupancy data
resource "azurerm_storage_container" "occupancy_data" {
  name                 = "occupancy-data"
  storage_account_id   = azurerm_storage_account.storage.id
}

# Blob Container for logs
resource "azurerm_storage_container" "logs" {
  name                 = "logs"
  storage_account_id   = azurerm_storage_account.storage.id
}

# Storage Account for Function App
resource "azurerm_storage_account" "function_storage" {
  name                     = local.function_storage_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  access_tier              = "Hot"
}

# Deployment blob containers (one per Function App)
resource "azurerm_storage_container" "collector_package" {
  name               = "collector-package"
  storage_account_id = azurerm_storage_account.function_storage.id
}

resource "azurerm_storage_container" "api_package" {
  name               = "api-package"
  storage_account_id = azurerm_storage_account.function_storage.id
}

# Application Insights
resource "azurerm_application_insights" "app_insights" {
  name                = "${local.project_name}-${local.environment}-insights"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  retention_in_days   = 30
}

# Service Plan — Flex Consumption (FC1)
resource "azurerm_service_plan" "function_plan" {
  name                = "${local.project_name}-${local.environment}-func-plan"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux"
  sku_name            = "FC1"
}

# --------------------------------------------------------------------------
# Function App 1: Collector (timer triggers — websocket listeners)
# --------------------------------------------------------------------------
# Deployed independently from the API so that dashboard changes never
# restart the always-ready collector instances.
resource "azurerm_function_app_flex_consumption" "collector" {
  name                = "${local.project_name}-${local.environment}-collector"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  service_plan_id     = azurerm_service_plan.function_plan.id

  runtime_name    = "python"
  runtime_version = "3.11"

  storage_authentication_type = "StorageAccountConnectionString"
  storage_access_key          = azurerm_storage_account.function_storage.primary_access_key
  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.function_storage.primary_blob_endpoint}collector-package"

  maximum_instance_count = 40
  instance_memory_in_mb  = 2048

  # Always-ready instances — timer triggers must fire reliably.
  always_ready {
    name           = "function:websocket_listener_even"
    instance_count = 1
  }

  always_ready {
    name           = "function:websocket_listener_odd"
    instance_count = 1
  }

  site_config {
    application_insights_key = azurerm_application_insights.app_insights.instrumentation_key
  }

  app_settings = {
    AZURE_STORAGE_ACCOUNT_NAME      = azurerm_storage_account.storage.name
    AZURE_STORAGE_ACCOUNT_KEY       = azurerm_storage_account.storage.primary_access_key
    AZURE_STORAGE_CONNECTION_STRING = azurerm_storage_account.storage.primary_connection_string
    BLOB_CONTAINER_NAME             = "occupancy-data"
    WEBSOCKET_URL                   = "wss://badi-public.crowdmonitor.ch:9591/api"
    TARGET_UID                      = "SSD-7"
    AzureWebJobsStorage             = azurerm_storage_account.function_storage.primary_connection_string
  }
}

# --------------------------------------------------------------------------
# Function App 2: API (HTTP triggers — dashboard, occupancy, health)
# --------------------------------------------------------------------------
# Can be deployed freely without affecting collector uptime.
resource "azurerm_function_app_flex_consumption" "api" {
  name                = "${local.project_name}-${local.environment}-api"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  service_plan_id     = azurerm_service_plan.function_plan.id

  runtime_name    = "python"
  runtime_version = "3.11"

  storage_authentication_type = "StorageAccountConnectionString"
  storage_access_key          = azurerm_storage_account.function_storage.primary_access_key
  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.function_storage.primary_blob_endpoint}api-package"

  maximum_instance_count = 40
  instance_memory_in_mb  = 2048

  site_config {
    application_insights_key = azurerm_application_insights.app_insights.instrumentation_key
  }

  app_settings = {
    AZURE_STORAGE_ACCOUNT_NAME      = azurerm_storage_account.storage.name
    AZURE_STORAGE_ACCOUNT_KEY       = azurerm_storage_account.storage.primary_access_key
    AZURE_STORAGE_CONNECTION_STRING = azurerm_storage_account.storage.primary_connection_string
    BLOB_CONTAINER_NAME             = "occupancy-data"
    AzureWebJobsStorage             = azurerm_storage_account.function_storage.primary_connection_string
  }
}
