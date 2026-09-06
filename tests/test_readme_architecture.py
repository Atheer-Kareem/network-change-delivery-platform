"""Portfolio SVG is standalone, accessible, and describes current authority."""

from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).parents[1]
SVG = ROOT / "docs/assets/ncdp-current-architecture.svg"
NS = {"s": "http://www.w3.org/2000/svg"}


def test_readme_embeds_accessible_current_architecture():
    root = ElementTree.parse(SVG).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["role"] == "img"
    for identity in root.attrib["aria-labelledby"].split():
        assert root.find(f".//*[@id='{identity}']") is not None
    readme = (ROOT / "README.md").read_text()
    assert "![Current NCDP architecture:" in readme
    assert "](docs/assets/ncdp-current-architecture.svg)" in readme
    texts = " ".join(element.text or "" for element in root.findall("s:text", NS))
    for phrase in (
        "PR / no live write",
        "Batfish first",
        "Exact-four · read-only",
        "NetBox + OpenBao",
        "Python control",
        "profiled-plan",
        "Human approval",
        "Exact plan digest",
        "profiled-deploy",
        "NCDP Live",
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
        "access-sw-01",
        "Current write projection: devices 1/2 only",
        "Independent validation",
        "AuditStore",
        "Oxidized",
        "Prometheus / Blackbox",
        "Grafana / Alertmanager",
        "Uncertain write → stop → no retry → independent reconciliation",
    ):
        assert phrase in texts
    for retired in ("deploy-gate", "promotion", "protected main", "PROTECTED MAIN"):
        assert retired not in texts
    assert len(root.findall("s:rect", NS)) < 20
    assert root.find(".//s:script", NS) is None
    assert root.find(".//s:image", NS) is None
    assert root.find(".//s:foreignObject", NS) is None
    assert "@import" not in SVG.read_text()
    assert "https://" not in SVG.read_text()
