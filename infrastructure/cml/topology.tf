resource "cml2_lab" "twin" {
  title       = "NCDP Terraform Twin"
  description = "Terraform-owned personal CML digital twin; no production configuration."
  notes       = "No production configuration and no stable management-address cutover."

  lifecycle {
    prevent_destroy = true
  }
}

resource "cml2_node" "system_bridge" {
  lab_id         = cml2_lab.twin.id
  label          = "system-bridge"
  nodedefinition = "external_connector"
  configuration  = one(local.system_bridge_matches).device_name
  tags           = ["terraform-stage-infra"]
  x              = -400
  y              = -200

  lifecycle {
    precondition {
      condition     = length(local.system_bridge_matches) == 1
      error_message = "Exactly one CML connector labelled System Bridge is required."
    }
  }
}

resource "cml2_node" "management_switch" {
  lab_id         = cml2_lab.twin.id
  label          = "management-switch"
  nodedefinition = "unmanaged_switch"
  tags           = ["terraform-stage-infra"]
  x              = -150
  y              = -200
}

resource "cml2_node" "core_02" {
  lab_id         = cml2_lab.twin.id
  label          = "core-02"
  nodedefinition = "cat8000v"
  imagedefinition = one(
    local.accepted_cat8000v_images
  ).id
  cpus = 1
  ram  = 4096
  tags = ["terraform-stage-router"]
  x    = 100
  y    = -400

  lifecycle {
    precondition {
      condition     = length(local.accepted_cat8000v_images) == 1
      error_message = "Exactly one CAT8000V image with ID cat8000v-17-18-02 is required."
    }
  }
}

resource "cml2_node" "edge_junos_01" {
  lab_id         = cml2_lab.twin.id
  label          = "edge-junos-01"
  nodedefinition = "vjunos-router"
  imagedefinition = one(
    local.accepted_vjunos_images
  ).id
  cpus = 4
  ram  = 6144
  tags = ["terraform-stage-router"]
  x    = 400
  y    = -200

  lifecycle {
    precondition {
      condition     = length(local.accepted_vjunos_images) == 1
      error_message = "Exactly one vJunos Router image with ID vjunos-router-23-2r1-15 is required."
    }
  }
}

resource "cml2_node" "core_03" {
  lab_id         = cml2_lab.twin.id
  label          = "core-03"
  nodedefinition = "cat8000v"
  imagedefinition = one(
    local.accepted_cat8000v_images
  ).id
  cpus = 1
  ram  = 4096
  tags = ["terraform-stage-router"]
  x    = 700
  y    = -400

  lifecycle {
    precondition {
      condition     = length(local.accepted_cat8000v_images) == 1
      error_message = "Exactly one CAT8000V image with ID cat8000v-17-18-02 is required."
    }
  }
}

resource "cml2_link" "system_bridge_management" {
  lab_id = cml2_lab.twin.id
  node_a = cml2_node.system_bridge.id
  slot_a = 0
  node_b = cml2_node.management_switch.id
  slot_b = 0
}

resource "cml2_link" "management_core_02" {
  lab_id = cml2_lab.twin.id
  node_a = cml2_node.management_switch.id
  slot_a = 1
  node_b = cml2_node.core_02.id
  slot_b = 0
}

resource "cml2_link" "management_edge_junos_01" {
  lab_id = cml2_lab.twin.id
  node_a = cml2_node.management_switch.id
  slot_a = 2
  node_b = cml2_node.edge_junos_01.id
  slot_b = 0
}

resource "cml2_link" "management_core_03" {
  lab_id = cml2_lab.twin.id
  node_a = cml2_node.management_switch.id
  slot_a = 3
  node_b = cml2_node.core_03.id
  slot_b = 0
}

resource "cml2_link" "core_02_edge_junos_01" {
  lab_id = cml2_lab.twin.id
  node_a = cml2_node.core_02.id
  slot_a = 3
  node_b = cml2_node.edge_junos_01.id
  slot_b = 1
}

resource "cml2_link" "edge_junos_01_core_03" {
  lab_id = cml2_lab.twin.id
  node_a = cml2_node.edge_junos_01.id
  slot_a = 2
  node_b = cml2_node.core_03.id
  slot_b = 2
}

resource "cml2_lifecycle" "twin" {
  lab_id = cml2_lab.twin.id
  state  = var.twin_lifecycle_state
  wait   = true

  update_triggers = {
    system_bridge     = "${cml2_node.system_bridge.id}:${cml2_node.system_bridge.generation}"
    management_switch = "${cml2_node.management_switch.id}:${cml2_node.management_switch.generation}"
    core_02           = "${cml2_node.core_02.id}:${cml2_node.core_02.generation}"
    edge_junos_01     = "${cml2_node.edge_junos_01.id}:${cml2_node.edge_junos_01.generation}"
    core_03           = "${cml2_node.core_03.id}:${cml2_node.core_03.generation}"
  }

  staging = {
    stages          = ["terraform-stage-infra", "terraform-stage-router"]
    start_remaining = false
  }

  timeouts = {
    create = "20m"
    update = "20m"
  }

  depends_on = [
    cml2_node.system_bridge,
    cml2_node.management_switch,
    cml2_node.core_02,
    cml2_node.edge_junos_01,
    cml2_node.core_03,
    cml2_link.system_bridge_management,
    cml2_link.management_core_02,
    cml2_link.management_edge_junos_01,
    cml2_link.management_core_03,
    cml2_link.core_02_edge_junos_01,
    cml2_link.edge_junos_01_core_03,
  ]
}
