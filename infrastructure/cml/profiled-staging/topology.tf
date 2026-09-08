resource "cml2_lab" "profiled_staging" {
  title       = "NCDP Staging ${var.staging_run_id}"
  description = "Disposable scoped read-only integration realization."
  notes       = "Terraform owns only this run-scoped CML realization."
}

resource "cml2_node" "system_bridge" {
  lab_id         = cml2_lab.profiled_staging.id
  label          = "system-bridge"
  nodedefinition = "external_connector"
  configuration  = one(local.system_bridge_matches).device_name
  tags           = ["profiled-staging-infrastructure"]
  x              = -400
  y              = -200

  lifecycle {
    precondition {
      condition     = length(local.system_bridge_matches) == 1
      error_message = "Exactly one CML System Bridge connector is required."
    }
  }
}

resource "cml2_node" "management_switch" {
  lab_id         = cml2_lab.profiled_staging.id
  label          = "management-switch"
  nodedefinition = "unmanaged_switch"
  tags           = ["profiled-staging-infrastructure"]
  x              = -150
  y              = -200
}

resource "cml2_node" "device" {
  for_each        = toset(nonsensitive(keys(var.devices)))
  lab_id          = cml2_lab.profiled_staging.id
  label           = replace(each.key, "_", "-")
  nodedefinition  = var.devices[each.key].node_definition
  imagedefinition = var.devices[each.key].image_definition
  configuration = sensitive(templatefile(
    "${path.module}/bootstrap/${var.devices[each.key].bootstrap_profile}.tftpl",
    {
      hostname        = var.devices[each.key].hostname
      management_cidr = var.devices[each.key].management_cidr
      username        = var.devices[each.key].username
      password_hash   = var.devices[each.key].password_verifier
    }
  ))
  cpus = var.devices[each.key].cpu_cores
  ram  = var.devices[each.key].ram_mb
  tags = ["profiled-staging-device"]
  x    = nonsensitive(var.devices[each.key].layout_x)
  y    = nonsensitive(var.devices[each.key].layout_y)
}

resource "cml2_link" "system_bridge_management" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.system_bridge.id
  slot_a = 0
  node_b = cml2_node.management_switch.id
  slot_b = 0
}

resource "cml2_link" "management" {
  for_each = toset(nonsensitive(keys(var.devices)))
  lab_id   = cml2_lab.profiled_staging.id
  node_a   = cml2_node.management_switch.id
  slot_a   = nonsensitive(var.devices[each.key].management_switch_slot)
  node_b   = cml2_node.device[each.key].id
  slot_b   = nonsensitive(var.devices[each.key].management_slot)
}

resource "cml2_link" "data" {
  for_each = var.data_links
  lab_id   = cml2_lab.profiled_staging.id
  node_a   = cml2_node.device[each.value.node_a].id
  slot_a   = each.value.slot_a
  node_b   = cml2_node.device[each.value.node_b].id
  slot_b   = each.value.slot_b
}

resource "cml2_lifecycle" "profiled_staging" {
  lab_id = cml2_lab.profiled_staging.id
  state  = var.lifecycle_state
  wait   = true

  update_triggers = {
    for name, node in cml2_node.device : name => "${node.id}:${node.generation}"
  }

  staging = {
    stages          = ["profiled-staging-infrastructure", "profiled-staging-device"]
    start_remaining = false
  }

  depends_on = [
    cml2_link.system_bridge_management,
    cml2_link.management,
    cml2_link.data,
  ]
}
