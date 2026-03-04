# === Deployment Provider Protocol and Factory (src_baton_providers___init__) v1 ===
#  Dependencies: baton.schemas, baton.providers.local, baton.providers.gcp, baton.providers.aws
# Defines the DeploymentProvider protocol interface for cloud deployment providers and provides a factory function to create provider instances for local, GCP, and AWS platforms.

# Module invariants:
#   - create_provider only supports three provider types: 'local', 'gcp', 'aws'
#   - All DeploymentProvider implementations must implement deploy, teardown, and status methods
#   - deploy and status methods return CircuitState
#   - teardown method returns None

class DeploymentProvider:
    """Protocol defining the interface for cloud deployment providers. Specifies async methods for deploying, tearing down, and checking status of circuits."""
    pass

def create_provider(
    name: str,
) -> DeploymentProvider:
    """
    Factory function that creates and returns a deployment provider instance based on the provided name. Supports 'local', 'gcp', and 'aws' providers.

    Preconditions:
      - name must be one of: 'local', 'gcp', 'aws'

    Postconditions:
      - Returns a valid DeploymentProvider instance
      - For 'local': returns LocalProvider instance
      - For 'gcp': returns GCPProvider instance
      - For 'aws': returns AWSProvider instance

    Errors:
      - unknown_provider (ValueError): name is not 'local', 'gcp', or 'aws'
          message: Unknown provider: {name}. Available: local, gcp, aws

    Side effects: Dynamically imports provider modules (baton.providers.local, baton.providers.gcp, or baton.providers.aws)
    Idempotent: yes
    """
    ...

def deploy(
    circuit: CircuitSpec,
    target: DeploymentTarget,
) -> CircuitState:
    """
    Protocol method to deploy a circuit to a specified deployment target. Returns the resulting circuit state.

    Postconditions:
      - Returns CircuitState reflecting the deployment result

    Side effects: Performs deployment operations to the target environment
    Idempotent: no
    """
    ...

def teardown(
    circuit: CircuitSpec,
    target: DeploymentTarget,
) -> None:
    """
    Protocol method to teardown/destroy a deployed circuit from the specified target environment.

    Postconditions:
      - Circuit is removed from the deployment target

    Side effects: Destroys deployed resources in the target environment
    Idempotent: no
    """
    ...

def status(
    circuit: CircuitSpec,
    target: DeploymentTarget,
) -> CircuitState:
    """
    Protocol method to check the current status of a deployed circuit on the specified target.

    Postconditions:
      - Returns CircuitState reflecting the current deployment status

    Side effects: Queries the target environment for circuit status
    Idempotent: yes
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['DeploymentProvider', 'create_provider', 'deploy', 'teardown', 'status']
