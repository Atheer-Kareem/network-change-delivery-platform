terraform {
  required_version = "= 1.15.8"

  required_providers {
    cml2 = {
      source  = "CiscoDevNet/cml2"
      version = "= 0.9.3-beta1"
    }
  }

  backend "local" {}
}
