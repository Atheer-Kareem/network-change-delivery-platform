variable "staging_run_id" {
  description = "Unique, non-secret orchestration identity for one ephemeral staging run."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,39}$", var.staging_run_id))
    error_message = "staging_run_id must be 1-40 lowercase ASCII letters, digits, or hyphens and start with a letter or digit."
  }
}

variable "twin_lifecycle_state" {
  description = "Explicit desired CML lifecycle state. Required; no implicit lifecycle action is allowed."
  type        = string

  validation {
    condition     = contains(["DEFINED_ON_CORE", "STARTED", "STOPPED"], var.twin_lifecycle_state)
    error_message = "twin_lifecycle_state must be explicitly one of DEFINED_ON_CORE, STARTED, or STOPPED."
  }
}

variable "core_02_bootstrap_hostname" {
  description = "NetBox-authoritative hostname rendered into core-02 Day-0 bootstrap."
  type        = string
  nullable    = false
}

variable "core_02_bootstrap_management_cidr" {
  description = "NetBox-authoritative IPv4 CIDR rendered on core-02 GigabitEthernet1."
  type        = string
  nullable    = false
}

variable "core_02_bootstrap_username" {
  description = "OpenBao-authoritative local IOS XE management username."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "core_02_bootstrap_password" {
  description = "OpenBao-authoritative local IOS XE management password."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "edge_junos_01_bootstrap_hostname" {
  description = "NetBox-authoritative hostname rendered into edge-junos-01 Day-0 bootstrap."
  type        = string
  nullable    = false
}

variable "edge_junos_01_bootstrap_management_cidr" {
  description = "NetBox-authoritative IPv4 CIDR rendered on edge-junos-01 fxp0."
  type        = string
  nullable    = false
}

variable "edge_junos_01_bootstrap_username" {
  description = "OpenBao-authoritative non-root Junos management username."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "edge_junos_01_bootstrap_password_hash" {
  description = "Runtime-derived SHA-512-crypt verifier for the OpenBao-authoritative Junos password."
  type        = string
  sensitive   = true
  nullable    = false
}
