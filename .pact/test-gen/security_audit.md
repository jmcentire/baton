# Security Audit Report

**Generated:** 2026-03-03T22:39:39.481150

## Summary

- Critical: 3
- High: 0
- Medium: 0
- Low: 1
- Info: 0
- **Total: 4**

## CRITICAL (3)

- **_cmd_service** (src/baton/cli.py:1058) [NOT COVERED]
  - Pattern: variable: role
  - Complexity: 11
  - Suggestion: Ensure branch on 'role' is tested with both truthy and falsy values
- **_cmd_status** (src/baton/cli.py:1143) [NOT COVERED]
  - Pattern: variable: role
  - Complexity: 13
  - Suggestion: Ensure branch on 'role' is tested with both truthy and falsy values
- **_serialize_circuit** (src/baton/config.py:127) [NOT COVERED]
  - Pattern: variable: role
  - Complexity: 11
  - Suggestion: Ensure branch on 'role' is tested with both truthy and falsy values

## LOW (1)

- **slot** (src/baton/lifecycle.py:114) [covered]
  - Pattern: variable: role
  - Complexity: 9
  - Suggestion: Ensure branch on 'role' is tested with both truthy and falsy values
