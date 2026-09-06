output "lab_id" {
  value = cml2_lab.profiled_staging.id
}

output "lab_title" {
  value = cml2_lab.profiled_staging.title
}

output "node_ids" {
  value = merge(
    { system_bridge = cml2_node.system_bridge.id, management_switch = cml2_node.management_switch.id },
    { for name, node in cml2_node.device : name => node.id },
  )
}

output "link_ids" {
  value = {
    for name, link in {
      system_bridge_management = cml2_link.system_bridge_management
      management_core          = cml2_link.management_core
      management_junos         = cml2_link.management_junos
      management_transit       = cml2_link.management_transit
      management_access        = cml2_link.management_access
      core_junos               = cml2_link.core_junos
      core_transit             = cml2_link.core_transit
      junos_transit            = cml2_link.junos_transit
      core_access              = cml2_link.core_access
    } : name => link.id
  }
}
