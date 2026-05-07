#
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#

"""
Convert a structured YAML hardware specification into a rich, unambiguous
natural-language prompt for VerilogCoder.

Usage:
    from spec_parser import parse_spec
    prompt = parse_spec("specs/fsm_serial.yaml")
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict


def _render_interface(interface: Dict) -> str:
    lines = []
    lines.append("Interface:")
    for sig in interface.get("inputs", []):
        w = sig.get("width", 1)
        width_str = f" [{w-1}:0]" if w > 1 else ""
        desc = f" -- {sig['description']}" if sig.get("description") else ""
        lines.append(f"  - input{width_str}  {sig['name']}{desc}")
    for sig in interface.get("outputs", []):
        w = sig.get("width", 1)
        width_str = f" [{w-1}:0]" if w > 1 else ""
        desc = f" -- {sig['description']}" if sig.get("description") else ""
        lines.append(f"  - output{width_str} {sig['name']}{desc}")
    return "\n".join(lines)


def _render_clock_reset(interface: Dict) -> str:
    lines = []
    for sig in interface.get("inputs", []):
        if sig.get("type") == "clock":
            lines.append(f"Clock: {sig['name']}, triggered on {sig.get('edge', 'posedge')}.")
        if sig.get("type") in ("sync_reset", "async_reset"):
            style = "Synchronous" if sig["type"] == "sync_reset" else "Asynchronous"
            active = sig.get("active", "high")
            reset_to = sig.get("reset_to", "initial state")
            lines.append(f"Reset: {sig['name']} is {style} active-{active}; resets FSM to {reset_to}.")
    return "\n".join(lines)


def _render_internal_signals(signals: list) -> str:
    if not signals:
        return ""
    lines = ["Internal registers:"]
    for sig in signals:
        w = sig.get("width", 1)
        rv = sig.get("reset_value", 0)
        desc = sig.get("description", "")
        lines.append(f"  - reg [{w-1}:0] {sig['name']} (reset={rv}): {desc}")
    return "\n".join(lines)


def _render_states(states: list) -> str:
    lines = ["States:"]
    for s in states:
        lines.append(f"  {s['name']}: {s.get('description', '')}")
    return "\n".join(lines)


def _render_transitions(transitions: list, outputs_default: Dict) -> str:
    lines = ["State transitions (evaluated on posedge clk):"]
    grouped: Dict[str, list] = {}
    for t in transitions:
        grouped.setdefault(t["from"], []).append(t)

    for src, trans in grouped.items():
        lines.append(f"  From {src}:")
        for t in trans:
            cond = t.get("condition", "always")
            dst = t["to"]
            action = t.get("action", "")
            out = t.get("output", "")
            parts = []
            if action:
                parts.append(action)
            if out:
                parts.append(out)
            else:
                for sig, val in outputs_default.items():
                    parts.append(f"{sig} = {val}")
            side = (", ".join(parts)) if parts else ""
            line = f"    - if ({cond}) -> {dst}"
            if side:
                line += f"  [{side}]"
            lines.append(line)
    return "\n".join(lines)


def _render_exceptions(exceptions: list) -> str:
    if not exceptions:
        return ""
    lines = ["Corner cases and constraints:"]
    for e in exceptions:
        lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_constraints(constraints: Dict) -> str:
    lines = ["Implementation constraints:"]
    for k, v in constraints.items():
        if isinstance(v, bool) and v:
            lines.append(f"  - {k.replace('_', ' ')}")
        elif not isinstance(v, bool):
            lines.append(f"  - {k.replace('_', ' ')}: {v}")
    return "\n".join(lines)


def parse_spec(yaml_file: str) -> str:
    """Parse a YAML hardware spec file and return a structured prompt string."""
    path = Path(yaml_file)
    with path.open("r") as f:
        spec = yaml.safe_load(f)

    module = spec.get("module", {})
    interface = spec.get("interface", {})
    behavior = spec.get("behavior", {})
    constraints = spec.get("constraints", {})

    sections = []

    # Header
    sections.append(
        f"I would like you to implement a module named {module.get('name', 'TopModule')} "
        f"with the following interface. All input and output ports are one bit unless otherwise specified."
    )
    sections.append("")

    # Interface
    sections.append(_render_interface(interface))
    sections.append("")

    # Description
    if module.get("description"):
        sections.append(f"Description: {module['description']}")
        sections.append("")

    # Clock/reset
    cr = _render_clock_reset(interface)
    if cr:
        sections.append(cr)
        sections.append("")

    # FSM-specific content
    if behavior.get("type") == "FSM":
        states = behavior.get("states", [])
        transitions = behavior.get("transitions", [])
        outputs_default = behavior.get("outputs_default", {})
        internal_signals = behavior.get("internal_signals", [])
        exceptions = behavior.get("exceptions", [])

        sections.append(_render_states(states))
        sections.append("")

        if internal_signals:
            sections.append(_render_internal_signals(internal_signals))
            sections.append("")

        sections.append(_render_transitions(transitions, outputs_default))
        sections.append("")

        if exceptions:
            sections.append(_render_exceptions(exceptions))
            sections.append("")

    # Constraints
    if constraints:
        sections.append(_render_constraints(constraints))
        sections.append("")

    return "\n".join(sections).strip()


if __name__ == "__main__":
    import sys
    yaml_file = sys.argv[1] if len(sys.argv) > 1 else "specs/fsm_serial.yaml"
    print(parse_spec(yaml_file))
