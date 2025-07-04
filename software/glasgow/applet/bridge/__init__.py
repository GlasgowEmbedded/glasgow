"""
The ``bridge`` taxon groups applets that interface with external (out-of-tree) tools.

Examples: an applet whose sole function is to interface with flashrom or probe-rs.
Counterexamples: an applet that provides a socket but the protocol is either Glasgow-specific,
or generic and not specific to any particular tool; an applet that provides both in-tree end-user
functionality, and a subcommand to interface with an external tool.
"""
