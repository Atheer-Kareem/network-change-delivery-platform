variable "staging_run_id" {
  description = "Unique, non-secret orchestration identity for one ephemeral staging run."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,39}$", var.staging_run_id))
    error_message = "staging_run_id must be 1-40 lowercase ASCII letters, digits, or hyphens and start with a letter or digit."
  }
}

variable "lifecycle_state" {
  description = "Explicit desired CML lifecycle state. Required; no implicit lifecycle action is allowed."
  type        = string

  validation {
    condition     = contains(["DEFINED_ON_CORE", "STARTED", "STOPPED"], var.lifecycle_state)
    error_message = "lifecycle_state must be explicitly one of DEFINED_ON_CORE, STARTED, or STOPPED."
  }
}

variable "cisco_bootstrap_hostname" {
  description = "Authority-supplied hostname rendered into the Cisco staging Day-0 bootstrap."
  type        = string
  nullable    = false
}

variable "cisco_bootstrap_management_cidr" {
  description = "Authority-supplied IPv4 CIDR rendered on Cisco GigabitEthernet1."
  type        = string
  nullable    = false
}

variable "cisco_bootstrap_username" {
  description = "OpenBao-authoritative local IOS XE management username."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "cisco_bootstrap_password" {
  description = "OpenBao-authoritative local IOS XE management password."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "junos_bootstrap_hostname" {
  description = "Authority-supplied hostname rendered into the Junos staging Day-0 bootstrap."
  type        = string
  nullable    = false
}

variable "junos_bootstrap_management_cidr" {
  description = "Authority-supplied IPv4 CIDR rendered on Junos fxp0."
  type        = string
  nullable    = false
}

variable "junos_bootstrap_username" {
  description = "OpenBao-authoritative non-root Junos management username."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "junos_bootstrap_password_hash" {
  description = "Runtime-derived SHA-512-crypt verifier for the OpenBao-authoritative Junos password."
  type        = string
  sensitive   = true
  nullable    = false
}
