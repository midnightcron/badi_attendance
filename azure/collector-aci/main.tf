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
  prefix               = "${var.project_name}-${var.environment}"
  storage_account_name = "badiacidevyb1a"  # fixed — do not change; storage account names are immutable
  acr_name             = "badiacidevyb1a"  # fixed — matches storage account suffix
}

# ─── Resource Group ────────────────────────────────────────────────
resource "azurerm_resource_group" "rg" {
  name     = "${local.prefix}-aci-rg"
  location = var.location
}

# ─── Storage Account (data) ───────────────────────────────────────
# Separate from prod so dev testing does not touch production data.
resource "azurerm_storage_account" "storage" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  access_tier              = "Hot"
}

resource "azurerm_storage_table" "occupancy" {
  name                 = "occupancy"
  storage_account_name = azurerm_storage_account.storage.name
}

resource "azurerm_storage_table" "occupancy_patterns" {
  name                 = "occupancypatterns"
  storage_account_name = azurerm_storage_account.storage.name
}

resource "azurerm_storage_container" "occupancy_parquet" {
  name               = "occupancy-parquet"
  storage_account_id = azurerm_storage_account.storage.id
}

# ─── Container Registry (Basic SKU — ~$5/month) ──────────────────
resource "azurerm_container_registry" "acr" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = true # required for ACI image pull
}

# ─── Log Analytics (for container logs) ──────────────────────────
resource "azurerm_log_analytics_workspace" "logs" {
  name                = "${local.prefix}-aci-logs"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# ─── Container Instance ──────────────────────────────────────────
resource "azurerm_container_group" "collector" {
  name                = "${local.prefix}-collector"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  restart_policy      = "Always"
  ip_address_type     = "None" # no inbound traffic needed

  image_registry_credential {
    server   = azurerm_container_registry.acr.login_server
    username = azurerm_container_registry.acr.admin_username
    password = azurerm_container_registry.acr.admin_password
  }

  container {
    name   = "collector"
    image  = "${azurerm_container_registry.acr.login_server}/badi-collector:latest"
    cpu    = 0.25
    memory = 0.5

    environment_variables = {
      WEBSOCKET_URL          = var.websocket_url
      TARGET_UID             = var.target_uid
      TABLE_NAME             = "occupancy"
      TABLE_NAME_PATTERNS    = "occupancypatterns"
      STATS_INTERVAL_SECONDS = "300"
      LOG_LEVEL              = "INFO"
    }

    secure_environment_variables = {
      AZURE_STORAGE_CONNECTION_STRING = azurerm_storage_account.storage.primary_connection_string
    }
  }

  diagnostics {
    log_analytics {
      workspace_id  = azurerm_log_analytics_workspace.logs.workspace_id
      workspace_key = azurerm_log_analytics_workspace.logs.primary_shared_key
      log_type      = "ContainerInsights"
    }
  }

  tags = {
    project     = var.project_name
    environment = var.environment
    component   = "collector-aci"
  }

  # Terraform cannot read back secure_environment_variables or diagnostics workspace_key
  # from the Azure API so they always appear as diffs. Ignore top-level blocks that
  # contain sensitive values to prevent unintended container restarts.
  lifecycle {
    ignore_changes = [
      diagnostics,
      image_registry_credential,
    ]
  }
}
