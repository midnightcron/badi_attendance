output "resource_group_name" {
  description = "Resource group for the ACI collector"
  value       = azurerm_resource_group.rg.name
}

output "storage_account_name" {
  description = "Storage account for occupancy data"
  value       = azurerm_storage_account.storage.name
}

output "acr_login_server" {
  description = "ACR login server for docker push"
  value       = azurerm_container_registry.acr.login_server
}

output "acr_admin_username" {
  description = "ACR admin username"
  value       = azurerm_container_registry.acr.admin_username
  sensitive   = true
}

output "acr_admin_password" {
  description = "ACR admin password"
  value       = azurerm_container_registry.acr.admin_password
  sensitive   = true
}

output "container_group_name" {
  description = "Name of the ACI container group"
  value       = azurerm_container_group.collector.name
}

output "log_analytics_workspace_id" {
  description = "Log Analytics workspace ID (for querying logs)"
  value       = azurerm_log_analytics_workspace.logs.workspace_id
}
