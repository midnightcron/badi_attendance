output "storage_account_name" {
  description = "Name of the storage account"
  value       = azurerm_storage_account.storage.name
}

output "storage_account_key" {
  description = "Primary access key for storage account"
  value       = azurerm_storage_account.storage.primary_access_key
  sensitive   = true
}

output "collector_app_name" {
  description = "Name of the collector function app (timer triggers)"
  value       = azurerm_function_app_flex_consumption.collector.name
}

output "api_app_name" {
  description = "Name of the API function app (HTTP triggers)"
  value       = azurerm_function_app_flex_consumption.api.name
}

output "dashboard_url" {
  description = "URL of the occupancy dashboard"
  value       = "https://${azurerm_function_app_flex_consumption.api.default_hostname}/api/dashboard"
}

output "app_insights_key" {
  description = "Instrumentation key for Application Insights"
  value       = azurerm_application_insights.app_insights.instrumentation_key
  sensitive   = true
}

output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.rg.name
}

output "resource_group_id" {
  description = "ID of the resource group"
  value       = azurerm_resource_group.rg.id
}
