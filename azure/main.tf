terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

locals {
  project_name          = var.project_name
  environment           = var.environment
  function_storage_name = "badfuncsa3yz1"  # fixed — do not change; storage account names are immutable
}

# ── Resource Group ────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "rg" {
  name     = "${local.project_name}-${local.environment}-rg"
  location = var.location
}

# ── Function App runtime storage ──────────────────────────────────────────────
# Stores deployment packages for the API Function App.
resource "azurerm_storage_account" "function_storage" {
  name                     = local.function_storage_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  access_tier              = "Hot"
}

resource "azurerm_storage_container" "api_package" {
  name               = "api-package"
  storage_account_id = azurerm_storage_account.function_storage.id
}

# ── Monitoring ────────────────────────────────────────────────────────────────
resource "azurerm_application_insights" "app_insights" {
  name                = "${local.project_name}-${local.environment}-insights"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  retention_in_days   = 30
}

# ── Flex Consumption service plan (shared by API) ─────────────────────────────
resource "azurerm_service_plan" "function_plan" {
  name                = "${local.project_name}-${local.environment}-func-plan"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux"
  sku_name            = "FC1"
}

# ── ACI occupancy data storage (read-only reference) ─────────────────────────
# Managed by azure/collector-aci/ Terraform root.
# The API reads occupancy Table Storage from this account.
data "azurerm_storage_account" "aci_storage" {
  name                = var.aci_storage_account_name
  resource_group_name = var.aci_resource_group_name
}

# ── Function App: API ─────────────────────────────────────────────────────────
# HTTP triggers: dashboard, occupancy query, health check.
# Scales to zero when idle; deployed independently from the ACI collector.
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
    AZURE_STORAGE_CONNECTION_STRING = data.azurerm_storage_account.aci_storage.primary_connection_string
    TABLE_NAME                      = "occupancy"
    PARQUET_CONTAINER_NAME          = "occupancy-parquet"
    AzureWebJobsStorage             = azurerm_storage_account.function_storage.primary_connection_string
  }
}
