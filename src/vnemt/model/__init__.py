"""Common grid data model shared by the EMT core and (from v0.4) the phasor core."""

from vnemt.model.netlist import Element, Netlist, build_netlist, is_ground

__all__ = ["Element", "Netlist", "build_netlist", "is_ground"]
