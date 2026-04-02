"""Conftest — restrict test collection to tests/ directory only."""
import sys

# Ensure pytest only collects from this tests/ directory, not from
# the parent attack_simulators/ whose functions start with test_*.
collect_ignore_glob = ["../attack_simulators/*"]
