"""Post-build deployment for Penny.

Automatically deploys builds to accessible URLs:
- Static sites (React/Vite) → penny-builds nginx server → <project>.builds.khamel.com
- Backend services → OCI-Dev via rsync + systemd → <project>.deer-panga.ts.net
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration
BUILDS_BASE_URL = os.environ.get("PENNY_BUILDS_BASE_URL", "builds.khamel.com")
OCI_DEV_HOST = os.environ.get("PENNY_OCI_DEV_HOST", "100.126.13.70")
OCI_DEV_USER = os.environ.get("PENNY_OCI_DEV_USER", "ubuntu")
OCI_DEV_BUILDS_DIR = os.environ.get("PENNY_OCI_DEV_BUILDS_DIR", "~/builds")


async def deploy_build(project_path: Path) -> Optional[str]:
    """Deploy a completed build and return the accessible URL.

    Args:
        project_path: Path to the build directory (e.g., /app/builds/black-punters-site)

    Returns:
        Accessible URL for the deployment, or None if deployment failed/not applicable
    """
    if not project_path.exists():
        logger.error(f"Build path does not exist: {project_path}")
        return None

    project_name = project_path.name
    logger.info(f"Deploying build: {project_name}")

    # Detect build type and deploy accordingly
    build_type = _detect_build_type(project_path)
    logger.info(f"Detected build type: {build_type}")

    if build_type == "static":
        return await _deploy_static_site(project_path, project_name)
    elif build_type == "python":
        return await _deploy_to_oci_dev(project_path, project_name, "python")
    elif build_type == "node":
        return await _deploy_to_oci_dev(project_path, project_name, "node")
    else:
        logger.warning(f"Unknown build type for {project_name}, skipping deployment")
        return None


def _detect_build_type(project_path: Path) -> str:
    """Detect the type of build based on project structure.

    Returns:
        'static' - React/Vite/static site with dist/ or build/ folder
        'python' - Python backend with requirements.txt
        'node' - Node.js backend with package.json but no static output
        'unknown' - Cannot determine type
    """
    # Check for static site output first (highest priority)
    dist_path = project_path / "dist"
    build_path = project_path / "build"

    if dist_path.exists() and (dist_path / "index.html").exists():
        return "static"
    if build_path.exists() and (build_path / "index.html").exists():
        return "static"

    # Check for Python backend
    if (project_path / "requirements.txt").exists():
        return "python"

    # Check for Node.js backend (has package.json but no static output)
    if (project_path / "package.json").exists():
        # If there's a server.js or app.js, it's likely a backend
        if (project_path / "server.js").exists() or (project_path / "app.js").exists():
            return "node"
        # If there's a src folder with no dist, might need to build first
        if (project_path / "src").exists() and not dist_path.exists():
            # Try to run the build
            return "needs_build"

    return "unknown"


async def _deploy_static_site(project_path: Path, project_name: str) -> str:
    """Deploy a static site - it's already accessible via penny-builds nginx.

    The penny-builds nginx container mounts /mnt/storage/penny/builds and
    serves <project>.builds.khamel.com from /<project>/dist/ or /<project>/build/.

    Args:
        project_path: Path to the build directory
        project_name: Name of the project (used in URL)

    Returns:
        URL where the site is accessible
    """
    url = f"https://{project_name}.{BUILDS_BASE_URL}"
    logger.info(f"Static site deployed at: {url}")

    # Verify the build output exists
    dist_path = project_path / "dist"
    build_path = project_path / "build"

    if dist_path.exists():
        file_count = len(list(dist_path.rglob("*")))
        logger.info(f"dist/ contains {file_count} files")
    elif build_path.exists():
        file_count = len(list(build_path.rglob("*")))
        logger.info(f"build/ contains {file_count} files")

    return url


async def _deploy_to_oci_dev(
    project_path: Path,
    project_name: str,
    runtime: str,
) -> Optional[str]:
    """Deploy a backend service to OCI-Dev via rsync + systemd.

    Args:
        project_path: Path to the build directory
        project_name: Name of the project
        runtime: 'python' or 'node'

    Returns:
        URL where the service is accessible, or None if deployment failed
    """
    logger.info(f"Deploying {runtime} service to OCI-Dev: {project_name}")

    try:
        # Rsync the project to OCI-Dev
        rsync_cmd = [
            "rsync", "-avz", "--delete",
            "--exclude=node_modules",
            "--exclude=.venv",
            "--exclude=__pycache__",
            "--exclude=.git",
            "--exclude=*.pyc",
            f"{project_path}/",
            f"{OCI_DEV_USER}@{OCI_DEV_HOST}:{OCI_DEV_BUILDS_DIR}/{project_name}/",
        ]

        proc = await asyncio.create_subprocess_exec(
            *rsync_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"rsync failed: {stderr.decode()}")
            return None

        logger.info(f"rsync completed: {stdout.decode()[:200]}")

        # Detect entry point and port
        entry_point, port = _detect_entry_point(project_path, runtime)
        if not entry_point:
            logger.error(f"Could not detect entry point for {project_name}")
            return None

        # Create and start systemd service
        await _setup_systemd_service(project_name, runtime, entry_point, port)

        # Return the Tailscale URL
        url = f"http://{project_name}.deer-panga.ts.net:{port}"
        logger.info(f"Backend service deployed at: {url}")
        return url

    except Exception as e:
        logger.error(f"OCI-Dev deployment failed: {e}")
        return None


def _detect_entry_point(project_path: Path, runtime: str) -> tuple[str, int]:
    """Detect the entry point and port for a backend service.

    Returns:
        Tuple of (entry_point_command, port)
    """
    port = 8000  # Default port

    if runtime == "python":
        # Check for common Python entry points
        if (project_path / "main.py").exists():
            return "python main.py", port
        if (project_path / "app.py").exists():
            return "python app.py", port
        if (project_path / "app" / "main.py").exists():
            return "uvicorn app.main:app --host 0.0.0.0 --port 8000", port
        # FastAPI pattern
        for f in project_path.rglob("main.py"):
            if "app" in str(f):
                module = str(f.relative_to(project_path)).replace("/", ".").replace(".py", "")
                return f"uvicorn {module}:app --host 0.0.0.0 --port 8000", port

    elif runtime == "node":
        # Check package.json for start script
        package_json = project_path / "package.json"
        if package_json.exists():
            import json
            try:
                pkg = json.loads(package_json.read_text())
                if "scripts" in pkg and "start" in pkg["scripts"]:
                    return "npm start", 3000
            except Exception:
                pass

        if (project_path / "server.js").exists():
            return "node server.js", 3000
        if (project_path / "app.js").exists():
            return "node app.js", 3000
        if (project_path / "index.js").exists():
            return "node index.js", 3000

    return None, port


async def _setup_systemd_service(
    project_name: str,
    runtime: str,
    entry_point: str,
    port: int,
) -> None:
    """Create and start a systemd service on OCI-Dev.

    Args:
        project_name: Name of the project (used as service name)
        runtime: 'python' or 'node'
        entry_point: Command to start the service
        port: Port the service listens on
    """
    # Sanitize project name for systemd
    service_name = project_name.replace("_", "-").lower()

    # Build the working directory path
    work_dir = f"/home/{OCI_DEV_USER}/builds/{project_name}"

    # Determine the exec start command based on runtime
    if runtime == "python":
        exec_start = f"{work_dir}/venv/bin/{entry_point}"
        setup_cmd = f"cd {work_dir} && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    else:
        exec_start = entry_point
        setup_cmd = f"cd {work_dir} && npm install"

    # Create systemd service unit content
    service_unit = f"""[Unit]
Description=Penny Build - {project_name}
After=network.target

[Service]
Type=simple
User={OCI_DEV_USER}
WorkingDirectory={work_dir}
ExecStart={exec_start}
Restart=always
RestartSec=5
Environment=PORT={port}
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
"""

    # Commands to run on OCI-Dev
    setup_and_start = f"""
set -e

# Install dependencies
{setup_cmd}

# Write systemd service file
echo '{service_unit}' | sudo tee /etc/systemd/system/{service_name}.service > /dev/null

# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable {service_name}
sudo systemctl restart {service_name}

# Check status
sleep 2
sudo systemctl status {service_name} --no-pager || true
"""

    ssh_cmd = [
        "ssh", f"{OCI_DEV_USER}@{OCI_DEV_HOST}",
        "bash", "-c", setup_and_start,
    ]

    proc = await asyncio.create_subprocess_exec(
        *ssh_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.warning(f"systemd setup may have issues: {stderr.decode()}")
    else:
        logger.info(f"systemd service {service_name} started: {stdout.decode()[:500]}")


async def run_build_command(project_path: Path) -> bool:
    """Run npm build if the project needs it.

    Args:
        project_path: Path to the project

    Returns:
        True if build succeeded, False otherwise
    """
    if not (project_path / "package.json").exists():
        return True  # No build needed

    dist_path = project_path / "dist"
    if dist_path.exists():
        return True  # Already built

    logger.info(f"Running npm build for {project_path.name}")

    # Install dependencies and build
    try:
        # npm install
        proc = await asyncio.create_subprocess_exec(
            "npm", "install",
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        if proc.returncode != 0:
            logger.error("npm install failed")
            return False

        # npm run build
        proc = await asyncio.create_subprocess_exec(
            "npm", "run", "build",
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"npm build failed: {stderr.decode()}")
            return False

        logger.info("npm build succeeded")
        return True

    except Exception as e:
        logger.error(f"Build command failed: {e}")
        return False
