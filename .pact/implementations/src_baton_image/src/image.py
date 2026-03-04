"""Container image building for Baton services.

Detects project type, generates Dockerfiles, builds and pushes images.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from baton.schemas import ImageInfo
from baton.state import ensure_baton_dir

logger = logging.getLogger(__name__)

IMAGES_FILE = "images.json"

_PYTHON_DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt* pyproject.toml* ./
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || pip install --no-cache-dir . 2>/dev/null || true
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD {cmd}
"""

_NODE_DOCKERFILE = """\
FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --production
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD {cmd}
"""


class ImageBuilder:
    """Build and manage container images for circuit nodes."""

    def __init__(self, project_dir: str | Path, circuit_name: str = "baton"):
        self._project_dir = Path(project_dir)
        self._circuit_name = circuit_name

    def detect_runtime(self, service_dir: str | Path) -> str:
        """Detect the runtime type of a service directory.

        Returns "python" or "node".
        """
        d = Path(service_dir)
        if (d / "package.json").exists():
            return "node"
        # Default to python for pyproject.toml, requirements.txt, or anything else
        return "python"

    def generate_dockerfile(
        self, node_name: str, service_dir: str | Path
    ) -> Path:
        """Generate a Dockerfile for a node's service. Returns path to Dockerfile."""
        d = Path(service_dir)
        runtime = self.detect_runtime(d)

        if runtime == "node":
            entry = self._detect_node_entry(d)
            cmd = json.dumps(["node", entry])
            content = _NODE_DOCKERFILE.format(cmd=cmd)
        else:
            entry = self._detect_python_entry(d)
            cmd = json.dumps(entry)
            content = _PYTHON_DOCKERFILE.format(cmd=cmd)

        dockerfile_dir = ensure_baton_dir(self._project_dir) / "dockerfiles"
        dockerfile_dir.mkdir(exist_ok=True)
        dockerfile_path = dockerfile_dir / f"Dockerfile.{node_name}"
        dockerfile_path.write_text(content)

        logger.info(f"Generated Dockerfile for [{node_name}] at {dockerfile_path}")
        return dockerfile_path

    async def build(
        self,
        node_name: str,
        service_dir: str | Path,
        tag: str = "",
    ) -> ImageInfo:
        """Build a Docker image for a node's service."""
        d = Path(service_dir)
        if not tag:
            tag = f"{self._circuit_name}-{node_name}:latest"

        # Generate Dockerfile if it doesn't exist
        dockerfile_dir = ensure_baton_dir(self._project_dir) / "dockerfiles"
        dockerfile_path = dockerfile_dir / f"Dockerfile.{node_name}"
        if not dockerfile_path.exists():
            dockerfile_path = self.generate_dockerfile(node_name, d)

        proc = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", tag,
            "-f", str(dockerfile_path),
            str(d),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"Docker build failed for [{node_name}]: {stderr.decode()}"
            )

        # Extract digest if available
        digest = ""
        for line in stdout.decode().splitlines():
            if "sha256:" in line:
                parts = line.split("sha256:")
                if len(parts) > 1:
                    digest = "sha256:" + parts[1].strip().split()[0]
                    break

        info = ImageInfo(
            node_name=node_name,
            tag=tag,
            built_at=datetime.now(timezone.utc).isoformat(),
            digest=digest,
        )
        self._save_image_info(info)
        logger.info(f"Built image [{node_name}]: {tag}")
        return info

    async def push(self, tag: str) -> str:
        """Push an image to its registry. Returns the pushed tag."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "push", tag,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Docker push failed for {tag}: {stderr.decode()}")

        logger.info(f"Pushed image: {tag}")
        return tag

    def list_images(self) -> list[ImageInfo]:
        """List all built images from .baton/images.json."""
        path = Path(self._project_dir) / ".baton" / IMAGES_FILE
        if not path.exists():
            return []
        with open(path) as f:
            data = json.load(f)
        return [ImageInfo(**item) for item in data]

    def _save_image_info(self, info: ImageInfo) -> None:
        """Save image info to .baton/images.json."""
        path = ensure_baton_dir(self._project_dir) / IMAGES_FILE
        images: list[dict] = []
        if path.exists():
            with open(path) as f:
                images = json.load(f)

        # Update existing entry for same node or append
        found = False
        for i, item in enumerate(images):
            if item.get("node_name") == info.node_name:
                images[i] = info.model_dump()
                found = True
                break
        if not found:
            images.append(info.model_dump())

        with open(path, "w") as f:
            json.dump(images, f, indent=2)

    def _detect_python_entry(self, service_dir: Path) -> list[str]:
        """Detect Python entry point from pyproject.toml or defaults."""
        pyproject = service_dir / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text()
            # Simple TOML parsing for [project.scripts]
            in_scripts = False
            for line in content.splitlines():
                if line.strip() == "[project.scripts]":
                    in_scripts = True
                    continue
                if in_scripts:
                    if line.strip().startswith("["):
                        break
                    if "=" in line:
                        # e.g. baton = "baton.cli:main"
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        module = val.split(":")[0]
                        return ["python", "-m", module]

        # Check for common entry points
        if (service_dir / "app.py").exists():
            return ["python", "app.py"]
        if (service_dir / "main.py").exists():
            return ["python", "main.py"]
        if (service_dir / "app" / "__init__.py").exists():
            return ["python", "-m", "app"]

        return ["python", "-m", "app"]

    def _detect_node_entry(self, service_dir: Path) -> str:
        """Detect Node.js entry point from package.json or defaults."""
        pkg = service_dir / "package.json"
        if pkg.exists():
            data = json.loads(pkg.read_text())
            # Check scripts.start
            start_script = data.get("scripts", {}).get("start", "")
            if start_script and start_script.startswith("node "):
                return start_script.split("node ", 1)[1].strip()
            # Check main field
            main = data.get("main", "")
            if main:
                return main

        if (service_dir / "index.js").exists():
            return "index.js"
        if (service_dir / "server.js").exists():
            return "server.js"
        if (service_dir / "app.js").exists():
            return "app.js"

        return "index.js"
