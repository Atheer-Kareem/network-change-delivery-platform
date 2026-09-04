resource "cml2_lab" "profiled_staging" {
  title       = "NCDP Staging ${var.staging_run_id}"
  description = "Disposable profiled exact-four read-only integration realization."
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
  for_each        = toset(["core_02", "edge_junos_01", "transit_ios_01", "access_sw_01"])
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
  x    = each.key == "core_02" ? 100 : each.key == "edge_junos_01" ? 400 : 250
  y    = each.key == "core_02" ? -400 : each.key == "edge_junos_01" ? -200 : 100
}

resource "cml2_link" "system_bridge_management" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.system_bridge.id
  slot_a = 0
  node_b = cml2_node.management_switch.id
  slot_b = 0
}

resource "cml2_link" "management_core" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.management_switch.id
  slot_a = 1
  node_b = cml2_node.device["core_02"].id
  slot_b = 0
}

resource "cml2_link" "management_junos" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.management_switch.id
  slot_a = 2
  node_b = cml2_node.device["edge_junos_01"].id
  slot_b = 0
}

resource "cml2_link" "management_transit" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.management_switch.id
  slot_a = 3
  node_b = cml2_node.device["transit_ios_01"].id
  slot_b = 0
}

resource "cml2_link" "management_access" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.management_switch.id
  slot_a = 4
  node_b = cml2_node.device["access_sw_01"].id
  slot_b = 0
}

resource "cml2_link" "core_junos" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.device["core_02"].id
  slot_a = 3
  node_b = cml2_node.device["edge_junos_01"].id
  slot_b = 1
}

resource "cml2_link" "core_transit" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.device["core_02"].id
  slot_a = 1
  node_b = cml2_node.device["transit_ios_01"].id
  slot_b = 1
}

resource "cml2_link" "junos_transit" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.device["edge_junos_01"].id
  slot_a = 2
  node_b = cml2_node.device["transit_ios_01"].id
  slot_b = 2
}

resource "cml2_link" "core_access" {
  lab_id = cml2_lab.profiled_staging.id
  node_a = cml2_node.device["core_02"].id
  slot_a = 2
  node_b = cml2_node.device["access_sw_01"].id
  slot_b = 1
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
    cml2_link.management_core,
    cml2_link.management_junos,
    cml2_link.management_transit,
    cml2_link.management_access,
    cml2_link.core_junos,
    cml2_link.core_transit,
    cml2_link.junos_transit,
    cml2_link.core_access,
  ]
}
