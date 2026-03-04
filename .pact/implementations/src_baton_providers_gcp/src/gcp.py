"""GCP Cloud Run deployment provider.

Deploys circuit nodes as Cloud Run services. Each node becomes a
Cloud Run service with its own URL. Edges are realized via
BATON_<TARGET>_URL environment variables injected into each service.

Requires: google-cloud-run>=0.10
Install: pip install baton[gcp]
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from baton.schemas import (
    AdapterState,
    CircuitSpec,
    CircuitState,
    CollapseLevel,
    DeploymentTarget,
    NodeStatus,
    ServiceSlot,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _service_id(circuit_name: str, node_name: str, namespace: str) -> str:
    """Generate a Cloud Run service ID from circuit + node name."""
    parts = [namespace, circuit_name, node_name] if namespace else [circuit_name, node_name]
    return "-".join(parts).lower().replace("_", "-")


class GCPProvider:
    """Deploy circuit nodes as Google Cloud Run services."""

    def __init__(self) -> None:
        self._service_urls: dict[str, str] = {}

    async def deploy(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        """Deploy each node as a Cloud Run service.

        Required target config:
            project: GCP project ID
        Optional:
            region: GCP region (default: us-central1)
            image_template: Docker image template with {node} placeholder
                           (default: "gcr.io/{project}/{circuit}-{node}:latest")
        """
        try:
            from google.cloud import run_v2
        except ImportError:
            raise RuntimeError(
                "GCP provider requires google-cloud-run. "
                "Install with: pip install baton[gcp]"
            )

        project = target.config.get("project")
        if not project:
            raise ValueError("GCP provider requires 'project' in deployment config")

        region = target.region or "us-central1"
        namespace = target.namespace
        image_template = target.config.get(
            "image_template",
            f"gcr.io/{project}/{circuit.name}-{{node}}:latest",
        )

        # Build images if requested
        if target.config.get("build") == "true":
            from baton.image import ImageBuilder

            project_dir = target.config.get("project_dir", ".")
            builder = ImageBuilder(project_dir, circuit_name=circuit.name)

            for node in circuit.nodes:
                service_dir = (node.metadata or {}).get("service_dir", "")
                if not service_dir:
                    logger.warning(
                        f"[{node.name}] No service_dir in metadata, skipping build"
                    )
                    continue

                tag = image_template.format(node=node.name)
                info = await builder.build(node.name, service_dir, tag=tag)
                await builder.push(tag)
                logger.info(f"Built and pushed [{node.name}]: {tag}")

        client = run_v2.ServicesAsyncClient()
        parent = f"projects/{project}/locations/{region}"

        state = CircuitState(
            circuit_name=circuit.name,
            collapse_level=CollapseLevel.FULL_LIVE,
            started_at=_now_iso(),
            updated_at=_now_iso(),
        )

        # First pass: create/update services
        for node in circuit.nodes:
            service_id = _service_id(circuit.name, node.name, namespace)
            image = image_template.format(node=node.name)

            # Build env vars: inject URLs of neighbor services
            # Note: PORT is reserved by Cloud Run and set automatically
            env_vars = {
                "BATON_NODE_NAME": node.name,
            }

            service = run_v2.Service(
                template=run_v2.RevisionTemplate(
                    containers=[
                        run_v2.Container(
                            image=image,
                            ports=[run_v2.ContainerPort(container_port=8080)],
                            env=[
                                run_v2.EnvVar(name=k, value=v)
                                for k, v in env_vars.items()
                            ],
                        )
                    ],
                ),
            )

            try:
                operation = await client.create_service(
                    parent=parent,
                    service=service,
                    service_id=service_id,
                )
                result = await operation.result()
                url = result.uri
                self._service_urls[node.name] = url
                logger.info(f"Deployed [{node.name}] as {service_id} -> {url}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    # Update existing service
                    service.name = f"{parent}/services/{service_id}"
                    operation = await client.update_service(service=service)
                    result = await operation.result()
                    url = result.uri
                    self._service_urls[node.name] = url
                    logger.info(f"Updated [{node.name}] as {service_id} -> {url}")
                else:
                    logger.error(f"Failed to deploy [{node.name}]: {e}")
                    state.adapters[node.name] = AdapterState(
                        node_name=node.name,
                        status=NodeStatus.FAULTED,
                    )
                    continue

            state.adapters[node.name] = AdapterState(
                node_name=node.name,
                status=NodeStatus.ACTIVE,
                service=ServiceSlot(
                    command=image,
                    is_mock=False,
                    started_at=_now_iso(),
                ),
            )
            state.live_nodes.append(node.name)

        # Make all services publicly accessible
        for node in circuit.nodes:
            service_id = _service_id(circuit.name, node.name, namespace)
            try:
                from google.iam.v1 import policy_pb2

                resource = f"{parent}/services/{service_id}"
                policy = policy_pb2.Policy(
                    bindings=[
                        policy_pb2.Binding(
                            role="roles/run.invoker",
                            members=["allUsers"],
                        )
                    ]
                )
                await client.set_iam_policy(
                    request={"resource": resource, "policy": policy}
                )
            except Exception as e:
                logger.warning(f"Could not set IAM policy for [{node.name}]: {e}")

        # Second pass: inject neighbor URLs as env vars
        if self._service_urls:
            for node in circuit.nodes:
                neighbors = circuit.neighbors(node.name)
                if not neighbors:
                    continue

                neighbor_env = {}
                for nb in neighbors:
                    url = self._service_urls.get(nb)
                    if url:
                        env_key = f"BATON_{nb.upper().replace('-', '_')}_URL"
                        neighbor_env[env_key] = url

                if not neighbor_env:
                    continue

                service_id = _service_id(circuit.name, node.name, namespace)
                image = image_template.format(node=node.name)

                all_env = {"BATON_NODE_NAME": node.name}
                all_env.update(neighbor_env)

                service = run_v2.Service(
                    name=f"{parent}/services/{service_id}",
                    template=run_v2.RevisionTemplate(
                        containers=[
                            run_v2.Container(
                                image=image,
                                ports=[run_v2.ContainerPort(container_port=8080)],
                                env=[
                                    run_v2.EnvVar(name=k, value=v)
                                    for k, v in all_env.items()
                                ],
                            )
                        ],
                    ),
                )

                try:
                    operation = await client.update_service(service=service)
                    await operation.result()
                    logger.info(
                        f"Updated [{node.name}] with neighbor URLs: "
                        f"{list(neighbor_env.keys())}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not update [{node.name}] with neighbor URLs: {e}"
                    )

        state.updated_at = _now_iso()
        return state

    async def teardown(self, circuit: CircuitSpec, target: DeploymentTarget) -> None:
        """Delete all Cloud Run services for this circuit."""
        try:
            from google.cloud import run_v2
        except ImportError:
            raise RuntimeError("GCP provider requires google-cloud-run")

        project = target.config.get("project")
        if not project:
            raise ValueError("GCP provider requires 'project' in deployment config")

        region = target.region or "us-central1"
        namespace = target.namespace
        parent = f"projects/{project}/locations/{region}"
        client = run_v2.ServicesAsyncClient()

        for node in circuit.nodes:
            service_id = _service_id(circuit.name, node.name, namespace)
            name = f"{parent}/services/{service_id}"
            try:
                operation = await client.delete_service(name=name)
                await operation.result()
                logger.info(f"Deleted [{node.name}] ({service_id})")
            except Exception as e:
                logger.warning(f"Could not delete [{node.name}]: {e}")

        self._service_urls.clear()

    async def status(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        """Check status of Cloud Run services."""
        try:
            from google.cloud import run_v2
        except ImportError:
            raise RuntimeError("GCP provider requires google-cloud-run")

        project = target.config.get("project")
        if not project:
            raise ValueError("GCP provider requires 'project' in deployment config")

        region = target.region or "us-central1"
        namespace = target.namespace
        parent = f"projects/{project}/locations/{region}"
        client = run_v2.ServicesAsyncClient()

        state = CircuitState(
            circuit_name=circuit.name,
            started_at=_now_iso(),
            updated_at=_now_iso(),
        )

        for node in circuit.nodes:
            service_id = _service_id(circuit.name, node.name, namespace)
            name = f"{parent}/services/{service_id}"
            try:
                svc = await client.get_service(name=name)
                url = svc.uri
                self._service_urls[node.name] = url

                # Check conditions for readiness
                # Cloud Run v2 uses integer enums: state=4 is CONDITION_SUCCEEDED
                # Condition types are RoutesReady and ConfigurationsReady
                ready = all(
                    any(
                        c.type_ == ctype and c.state.value == 4
                        for c in (svc.conditions or [])
                    )
                    for ctype in ("RoutesReady", "ConfigurationsReady")
                )

                state.adapters[node.name] = AdapterState(
                    node_name=node.name,
                    status=NodeStatus.ACTIVE if ready else NodeStatus.LISTENING,
                    service=ServiceSlot(
                        command=url,
                        is_mock=False,
                        started_at=_now_iso(),
                    ),
                )
                if ready:
                    state.live_nodes.append(node.name)
            except Exception as e:
                state.adapters[node.name] = AdapterState(
                    node_name=node.name,
                    status=NodeStatus.IDLE,
                )
                logger.debug(f"Could not get status for [{node.name}]: {e}")

        total = len(circuit.nodes)
        live = len(state.live_nodes)
        if live == 0:
            state.collapse_level = CollapseLevel.FULL_MOCK
        elif live == total:
            state.collapse_level = CollapseLevel.FULL_LIVE
        else:
            state.collapse_level = CollapseLevel.PARTIAL

        return state
