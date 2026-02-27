## ──────────────────────────────────────────────────────────────────
## PRODUCTION environment (Functions-based collector + API)
## ──────────────────────────────────────────────────────────────────
## Azure resource names contain "dev" for historical reasons.
## This IS the production deployment — do NOT change resource names
## or the environment variable, as that would destroy/recreate resources.
##
## The new ACI-based collector lives in azure/collector-aci/ (dev env).
## ──────────────────────────────────────────────────────────────────

location        = "westeurope"
project_name    = "badi-oerlikon"
environment     = "dev"            # ← keeps existing Azure resource names
subscription_id = "cc569079-9e12-412d-8dfb-a5d60a028f75"
