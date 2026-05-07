"""
network_monitor.py
==================
Monitors a 4-router OSPF + BGP topology and generates an HTML report.

Routers: R1, R2 (AS65001) and R4 (AS65002), with R3 as OSPF-only.
- Collects OSPF neighbors, BGP sessions, and routing tables via Docker exec
- Detects anomalies (down neighbors, missing routes)
- Generates an HTML report for portfolio demonstration

Author: Ikhlas Retbi
"""

import subprocess
import json
import re
from datetime import datetime
from pathlib import Path
from jinja2 import Template
from rich.console import Console
from rich.table import Table

console = Console()

ROUTERS = ["R1", "R2", "R3", "R4"]


def run_vtysh(router: str, command: str) -> str:
    """Execute a vtysh command inside a router container and return its output."""
    try:
        result = subprocess.run(
            ["docker", "exec", router, "vtysh", "-c", command],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout
    except Exception as e:
        return f"ERROR: {e}"


def parse_ospf_neighbors(output: str) -> list:
    """Parse the output of 'show ip ospf neighbor' into a list of dicts."""
    neighbors = []
    for line in output.splitlines():
        # Match lines like: "2.2.2.2  1  Full/DR  5m03s  ..."
        match = re.match(
            r"\s*(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\S+)\s+\S+\s+\S+\s+(\d+\.\d+\.\d+\.\d+)",
            line
        )
        if match:
            neighbors.append({
                "neighbor_id": match.group(1),
                "state": match.group(2),
                "address": match.group(3),
            })
    return neighbors


def parse_bgp_summary(output: str) -> list:
    """Parse 'show ip bgp summary' output into a list of peer dicts."""
    peers = []
    for line in output.splitlines():
        # Match BGP peer rows
        match = re.match(
            r"(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(\S+)",
            line
        )
        if match:
            peers.append({
                "peer_ip": match.group(1),
                "remote_as": match.group(2),
                "uptime": match.group(3),
            })
    return peers


def collect_router_data(router: str) -> dict:
    """Collect OSPF + BGP + route data from a single router."""
    console.print(f"[cyan]Collecting data from {router}...[/cyan]")
    return {
        "name": router,
        "ospf_neighbors": parse_ospf_neighbors(run_vtysh(router, "show ip ospf neighbor")),
        "bgp_peers": parse_bgp_summary(run_vtysh(router, "show ip bgp summary")),
        "routes_raw": run_vtysh(router, "show ip route"),
    }


def detect_anomalies(routers_data: list) -> list:
    """Detect issues in the collected data and return a list of warnings."""
    anomalies = []
    for r in routers_data:
        # Check OSPF neighbors not in Full state
        for n in r["ospf_neighbors"]:
            if "Full" not in n["state"]:
                anomalies.append(f"{r['name']}: OSPF neighbor {n['neighbor_id']} is in state {n['state']} (expected Full)")
        # Check BGP peers without uptime (down)
        for p in r["bgp_peers"]:
            if p["uptime"] in ("never", "Active", "Idle"):
                anomalies.append(f"{r['name']}: BGP peer {p['peer_ip']} (AS{p['remote_as']}) is {p['uptime']}")
    return anomalies


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Network Health Report</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 2rem; }
  h1 { color: #38bdf8; border-bottom: 2px solid #38bdf8; padding-bottom: 0.5rem; }
  h2 { color: #fbbf24; margin-top: 2rem; }
  .meta { color: #94a3b8; font-size: 0.9rem; margin-bottom: 2rem; }
  .router { background: #1e293b; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; border-left: 4px solid #10b981; }
  table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #334155; }
  th { background: #0f172a; color: #38bdf8; }
  .ok { color: #10b981; font-weight: bold; }
  .alert { color: #ef4444; font-weight: bold; }
  .anomaly { background: #7f1d1d; padding: 1rem; border-radius: 6px; margin-bottom: 0.5rem; border-left: 4px solid #ef4444; }
  pre { background: #0f172a; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; }
</style>
</head>
<body>
  <h1>Network Health Report</h1>
  <div class="meta">Generated: {{ timestamp }} &mdash; 4-router OSPF + BGP topology &mdash; AS65001 / AS65002</div>

  <h2>Summary</h2>
  {% if anomalies %}
    {% for a in anomalies %}<div class="anomaly">{{ a }}</div>{% endfor %}
  {% else %}
    <div class="anomaly" style="background:#064e3b;border-color:#10b981;">All systems healthy. No anomalies detected.</div>
  {% endif %}

  {% for r in routers %}
  <div class="router">
    <h2>{{ r.name }}</h2>

    <h3>OSPF Neighbors</h3>
    <table>
      <tr><th>Neighbor ID</th><th>Address</th><th>State</th></tr>
      {% for n in r.ospf_neighbors %}
      <tr>
        <td>{{ n.neighbor_id }}</td>
        <td>{{ n.address }}</td>
        <td class="{% if 'Full' in n.state %}ok{% else %}alert{% endif %}">{{ n.state }}</td>
      </tr>
      {% else %}
      <tr><td colspan="3">No OSPF neighbors</td></tr>
      {% endfor %}
    </table>

    <h3>BGP Peers</h3>
    <table>
      <tr><th>Peer IP</th><th>Remote AS</th><th>Uptime / State</th></tr>
      {% for p in r.bgp_peers %}
      <tr>
        <td>{{ p.peer_ip }}</td>
        <td>AS{{ p.remote_as }}</td>
        <td class="{% if p.uptime in ('never','Active','Idle') %}alert{% else %}ok{% endif %}">{{ p.uptime }}</td>
      </tr>
      {% else %}
      <tr><td colspan="3">No BGP peers</td></tr>
      {% endfor %}
    </table>

    <h3>Routing Table</h3>
    <pre>{{ r.routes_raw }}</pre>
  </div>
  {% endfor %}
</body>
</html>
"""


def generate_html_report(routers_data: list, anomalies: list, output: str):
    """Render the Jinja2 HTML template and save to file."""
    template = Template(HTML_TEMPLATE)
    html = template.render(
        routers=routers_data,
        anomalies=anomalies,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    Path(output).write_text(html, encoding="utf-8")
    console.print(f"[green]Report saved to {output}[/green]")


def print_terminal_summary(routers_data: list, anomalies: list):
    """Pretty-print a summary table to the terminal."""
    table = Table(title="Network Status Summary")
    table.add_column("Router", style="cyan")
    table.add_column("OSPF Neighbors", style="green")
    table.add_column("BGP Peers", style="yellow")

    for r in routers_data:
        table.add_row(r["name"], str(len(r["ospf_neighbors"])), str(len(r["bgp_peers"])))

    console.print(table)

    if anomalies:
        console.print("\n[red]Anomalies detected:[/red]")
        for a in anomalies:
            console.print(f"  - {a}")
    else:
        console.print("\n[green]All systems healthy.[/green]")


def main():
    console.print("[bold cyan]Network Automation Lab - Health Check[/bold cyan]\n")
    routers_data = [collect_router_data(r) for r in ROUTERS]
    anomalies = detect_anomalies(routers_data)
    print_terminal_summary(routers_data, anomalies)
    generate_html_report(routers_data, anomalies, "report.html")


if __name__ == "__main__":
    main()
