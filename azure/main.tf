terraform {
  required_version = ">= 1.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
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

# Blob Container for scraped data
resource "azurerm_storage_container" "scraped_data" {
  name                  = "scraped-data"
  storage_account_name  = azurerm_storage_account.storage.name
  container_access_type = "private"
}

# Blob Container for logs
resource "azurerm_storage_container" "logs" {
  name                  = "logs"
  storage_account_name  = azurerm_storage_account.storage.name
  container_access_type = "private"
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

# Application Insights
resource "azurerm_application_insights" "app_insights" {
  name                       = "${local.project_name}-${local.environment}-insights"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  application_type           = "web"
  retention_in_days          = 30
  disable_ip_masking         = false
}

# App Service Plan for Function (Consumption)
resource "azurerm_app_service_plan" "function_plan" {
  name                = "${local.project_name}-${local.environment}-func-plan"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "FunctionApp"
  reserved            = true

  sku {
    tier = "Dynamic"
    size = "Y1"
  }
}

# Function App
resource "azurerm_function_app" "function_app" {
  name                       = "${local.project_name}-${local.environment}-func"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  app_service_plan_id        = azurerm_app_service_plan.function_plan.id
  storage_account_name       = azurerm_storage_account.function_storage.name
  storage_account_access_key = azurerm_storage_account.function_storage.primary_access_key
  version                    = "~4"
  os_type                    = "linux"

  app_settings = {
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
    FUNCTIONS_EXTENSION_VERSION         = "~4"
    FUNCTIONS_WORKER_RUNTIME            = "python"
    FUNCTIONS_WORKER_RUNTIME_VERSION    = "3.11"
    APPINSIGHTS_INSTRUMENTATIONKEY      = azurerm_application_insights.app_insights.instrumentation_key
    AZURE_STORAGE_ACCOUNT_NAME          = azurerm_storage_account.storage.name
    AZURE_STORAGE_ACCOUNT_KEY           = azurerm_storage_account.storage.primary_access_key
    AZURE_STORAGE_CONNECTION_STRING     = azurerm_storage_account.storage.primary_connection_string
    BLOB_CONTAINER_NAME                 = azurerm_storage_container.scraped_data.name
    WEBSOCKET_URL                       = "wss://badi-public.crowdmonitor.ch:9591/api"
    TARGET_UID                          = "SSD-7"
    AzureWebJobsStorage                 = azurerm_storage_account.function_storage.primary_connection_string
    AzureWebJobsDashboard               = azurerm_storage_account.function_storage.primary_connection_string
  }
}
