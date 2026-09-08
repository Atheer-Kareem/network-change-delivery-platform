variable "staging_run_id" {
  type     = string
  nullable = false

  validation {
    condition     = can(regex("^[a-z0-9]+(?:[._-][a-z0-9]+)*$", var.staging_run_id))
    error_message = "staging_run_id must be a bounded lowercase run identity."
  }
}

variable "lifecycle_state" {
  type     = string
  nullable = false

  validation {
    condition     = contains(["DEFINED_ON_CORE", "STARTED", "STOPPED"], var.lifecycle_state)
    error_message = "lifecycle_state must be explicit."
  }
}

variable "devices" {
  description = "Sensitive profiled Day-0 values derived at runtime from exact inventory, OpenBao, and the realization catalog."
  sensitive   = true
  nullable    = false
  type = map(object({
    hostname               = string
    management_cidr        = string
    username               = string
    password_verifier      = string
    node_definition        = string
    image_definition       = string
    cpu_cores              = number
    ram_mb                 = number
    management_port        = number
    bootstrap_profile      = string
    management_slot        = number
    management_switch_slot = number
    layout_x               = number
    layout_y               = number
  }))

  validation {
    condition     = length(var.devices) > 0
    error_message = "devices must contain the Python-admitted nonempty scope."
  }
}

variable "data_links" {
  description = "Exact reviewed topology, admitted by Python against the device scope."
  nullable    = false
  type = map(object({
    node_a = string
    slot_a = number
    node_b = string
    slot_b = number
  }))
  validation {
    condition     = alltrue([for link in values(var.data_links) : contains(keys(var.devices), link.node_a) && contains(keys(var.devices), link.node_b) && link.node_a != link.node_b && link.slot_a >= 0 && link.slot_b >= 0])
    error_message = "Data links must reference admitted device-map endpoints."
  }
}
