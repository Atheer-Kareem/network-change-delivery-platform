variable "twin_lifecycle_state" {
  description = "Explicit desired CML lifecycle state. Required; no implicit lifecycle action is allowed."
  type        = string

  validation {
    condition = contains(
      ["DEFINED_ON_CORE", "STARTED", "STOPPED"],
      var.twin_lifecycle_state,
    )
    error_message = "twin_lifecycle_state must be explicitly one of DEFINED_ON_CORE, STARTED, or STOPPED."
  }
}

variable "core_02_bootstrap_hostname" {
  description = "NetBox-authoritative hostname rendered into the personal-lab core-02 Day-0 bootstrap."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9.-]{0,62}$", var.core_02_bootstrap_hostname))
    error_message = "core_02_bootstrap_hostname must be a valid IOS hostname with no whitespace or control characters."
  }
}

variable "core_02_bootstrap_management_cidr" {
  description = "NetBox-authoritative IPv4 CIDR rendered on core-02 GigabitEthernet1."
  type        = string
  nullable    = false

  validation {
    condition = (
      can(cidrnetmask(var.core_02_bootstrap_management_cidr)) &&
      length(regexall(":", var.core_02_bootstrap_management_cidr)) == 0
    )
    error_message = "core_02_bootstrap_management_cidr must be a valid IPv4 CIDR."
  }
}

variable "core_02_bootstrap_username" {
  description = "OpenBao-authoritative local IOS XE management username for the personal lab."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+$", var.core_02_bootstrap_username))
    error_message = "core_02_bootstrap_username contains characters unsafe for IOS Day-0 rendering."
  }
}

variable "core_02_bootstrap_password" {
  description = "OpenBao-authoritative local IOS XE management password for the personal lab."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition = (
      length(var.core_02_bootstrap_password) > 0 &&
      length(regexall("[\\r\\n\\t ]", var.core_02_bootstrap_password)) == 0
    )
    error_message = "core_02_bootstrap_password must be non-empty and contain no whitespace or control characters."
  }
}
