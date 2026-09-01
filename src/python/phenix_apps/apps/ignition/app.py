import json
import os
import re
import shutil
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from phenix_apps.apps import AppBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# Templates
TEMPLATES_DIR = utils.abs_path(__file__, "templates")
PERSPECTIVE_TEMPLATES_DIR = utils.abs_path(__file__, "templates/perspective")
API_TEMPLATES_DIR = utils.abs_path(__file__, "templates/api")
TAG_FOLDER_RESOURCE_FILE = f"{TEMPLATES_DIR}/tag-folder-resource.json"
# Auto-discover tags from returned DNP3 points
TAG_SYNC_TAG_FILE = f"{TEMPLATES_DIR}/tag-sync-tag.json"
TAG_SYNC_SCRIPT_FILE = f"{TEMPLATES_DIR}/tag-sync.py"

# hosts: types
GATEWAY_TYPE = "gateway"
PERSPECTIVE_TYPE = "perspective"

# Fixed project name for the WebDev tag API
API_PROJECT_NAME = "api"

# expect windows, built with /phenix/startup and /phenix/user-startup
GUEST_APP_DIR = "/phenix/ignition"
GUEST_GWBK_SCRIPT_DST = "/phenix/startup/98-ignition.ps1"
GUEST_CLIENT_SCRIPT_DST = "/phenix/user-startup/99-ignition-perspective.ps1"
# Ignition program paths
GUEST_DATA_DIR = "Program Files/Inductive Automation/Ignition/data"
GUEST_DEVICE_DIR = (
    f"{GUEST_DATA_DIR}/config/resources/core/com.inductiveautomation.opcua/device"
)
GUEST_TAG_DIR = (
    f"{GUEST_DATA_DIR}/config/resources/core/ignition/tag-definition/default"
)
GUEST_PROJECTS_DIR = f"{GUEST_DATA_DIR}/projects"


class RtuDeviceConfig(BaseModel):
    """DNP3 outstation connection settings RTU."""

    hostname: str
    name: str | None = None
    port: int = 20000
    # Default to ot-sim expectations
    source_address: int = 1
    destination_address: int = 1024
    interface: str | None = None

    model_config = {"extra": "ignore"}

    @property
    def resolved_name(self) -> str:
        return self.name or self.hostname


class PerspectiveConfig(BaseModel):
    """Perspective HMI options for a gateway (`perspective: true` for defaults)."""

    project: str = "hmi"
    open_client: bool = True

    model_config = {"extra": "ignore"}

    @field_validator("project")
    @classmethod
    def _validate_project_name(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", v):
            raise ValueError(
                "perspective project names may only contain letters, digits, "
                "'_' and '-'"
            )
        return v


class ApiConfig(BaseModel):
    """WebDev tag API options for a gateway (`api: true` for defaults).

    Serves a `tags` WebDev resource at
    `http://<gateway>:8088/system/webdev/api/tags`: GET reads every DNP3 point
    from the OPC server, POST issues a DNP3 command (binary CROB). `auth`
    requires HTTP Basic auth on the POST (control) endpoint, validated against
    `user_source` and optionally restricted to `roles`; reads stay open.
    """

    auth: bool = False
    roles: list[str] = Field(default_factory=list)
    user_source: str = "default"

    model_config = {"extra": "ignore"}


class IgnitionHostConfig(BaseModel):
    """Per-host metadata for a `type: gateway` node.

    With `connected_rtus`, rendered DNP3 device resources are injected into
    the gateway's config tree before boot, and `perspective` optionally builds
    a basic HMI project on top of them whose tags auto-import from whatever
    points the devices actually serve.

    With `gwbk`, the given gateway backup is
    restored verbatim at boot instead.

    `api` optionally serves a WebDev tag API and is independent of both
    `perspective` and `connected_rtus`. `gwbk` is mutually exclusive with the
    other options.
    """

    gwbk: str | None = None
    connected_rtus: list[RtuDeviceConfig] = Field(default_factory=list)
    perspective: PerspectiveConfig | None = None
    api: ApiConfig | None = None

    model_config = {"extra": "ignore"}

    @field_validator("connected_rtus", mode="before")
    @classmethod
    def _normalize_rtus(cls, v: Any) -> list[Any]:
        """Allow plain hostname strings alongside dict overrides."""
        if not v:
            return []
        return [{"hostname": e} if isinstance(e, str) else e for e in v]

    @field_validator("perspective", mode="before")
    @classmethod
    def _normalize_perspective(cls, v: Any) -> Any:
        """Allow `perspective: true` as shorthand for the defaults."""
        if v is True:
            return PerspectiveConfig()
        if v is False:
            return None
        return v

    @field_validator("api", mode="before")
    @classmethod
    def _normalize_api(cls, v: Any) -> Any:
        """Allow `api: true` as shorthand for the defaults."""
        if v is True:
            return ApiConfig()
        if v is False:
            return None
        return v

    @model_validator(mode="after")
    def _gwbk_excludes_extras(self) -> "IgnitionHostConfig":
        if self.gwbk and self.connected_rtus:
            raise ValueError(
                "'gwbk' restores a complete backup verbatim and cannot be "
                "combined with 'connected_rtus'; put the device connections "
                "in the backup itself"
            )
        if self.gwbk and self.perspective:
            raise ValueError(
                "'perspective' builds an HMI from connected_rtus and cannot be "
                "combined with 'gwbk'; add the HMI project to the backup itself"
            )
        if self.gwbk and self.api:
            raise ValueError(
                "'api' injects a WebDev project into the gateway's data tree "
                "and cannot be combined with 'gwbk'; add the api project to "
                "the backup itself"
            )
        return self


class PerspectiveClientConfig(BaseModel):
    """Per-host metadata for a `type: perspective` node (dedicated HMI desktop)."""

    connected_gateway: str | None = None
    interface: str | None = None

    model_config = {"extra": "ignore"}


class Ignition(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.app_dir: str = f"{self.exp_dir}/ignition"
        os.makedirs(self.app_dir, exist_ok=True)

    def pre_start(self) -> None:
        logger.info(f"Starting user application: {self.name}")

        perspective_gateways: dict[str, PerspectiveConfig] = {}
        for gateway in self.extract_nodes_type(GATEWAY_TYPE):
            cfg = self._configure_gateway(gateway)
            if cfg and cfg.perspective:
                perspective_gateways[gateway.hostname] = cfg.perspective

        for client in self.extract_nodes_type(PERSPECTIVE_TYPE):
            self._configure_perspective_client(client, perspective_gateways)

        logger.info(f"Started user application: {self.name}")

    def _configure_gateway(self, gateway) -> IgnitionHostConfig | None:
        hostname = gateway.hostname
        cfg = IgnitionHostConfig(**gateway.metadata)

        if not cfg.connected_rtus and not cfg.gwbk and not cfg.api:
            logger.warning(
                f"'{hostname}' has no connected_rtus, api, or gwbk; skipping"
            )
            return None

        host_dir = f"{self.app_dir}/{hostname}"
        os.makedirs(host_dir, exist_ok=True)

        if cfg.gwbk:
            if not os.path.isfile(cfg.gwbk):
                if not self.dryrun:
                    raise ValueError(f"gwbk '{cfg.gwbk}' not found")
                logger.warning(f"Dry run: gwbk '{cfg.gwbk}' not found; skipping")
                return None
            self.add_inject(
                hostname=hostname,
                inject={"src": cfg.gwbk, "dst": f"{GUEST_APP_DIR}/restore.gwbk"},
            )
            # only a gwbk restore needs boot-time work (gwcmd on the live guest)
            script = f"{host_dir}/98-ignition.ps1"
            with open(script, "w", newline="\r\n") as f:
                utils.mako_serve_template("98-ignition.ps1.mako", TEMPLATES_DIR, f)
            self.add_inject(
                hostname=hostname, inject={"src": script, "dst": GUEST_GWBK_SCRIPT_DST}
            )
        else:
            devices = self._resolve_devices(cfg.connected_rtus)
            self._validate_unique_names(devices)
            for src, dst in self._write_device_tree(host_dir, devices):
                self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})
            if cfg.perspective:
                self._write_perspective(hostname, host_dir, cfg.perspective, devices)
                if cfg.perspective.open_client:
                    url = (
                        "http://localhost:8088/data/perspective/client/"
                        f"{cfg.perspective.project}"
                    )
                    self._inject_open_client_script(hostname, host_dir, url)
            if cfg.api:
                self._write_api(hostname, host_dir, cfg.api)

        return cfg

    def _resolve_devices(self, rtus: list[RtuDeviceConfig]) -> list[dict[str, Any]]:
        devices = []

        for rtu in rtus:
            ip = self.extract_node_interface_ip(rtu.hostname, rtu.interface)
            if not ip:
                msg = (
                    f"RTU '{rtu.hostname}' has no addressed interface "
                    f"'{rtu.interface or '(first)'}' in the topology"
                )
                if not self.dryrun:
                    raise ValueError(msg)
                logger.warning(f"Dry run: {msg}; using placeholder IP")
                ip = "127.0.0.1"

            devices.append(
                {
                    "name": rtu.resolved_name,
                    "ip": ip,
                    "port": rtu.port,
                    "source_address": rtu.source_address,
                    "destination_address": rtu.destination_address,
                }
            )

        return devices

    @staticmethod
    def _validate_unique_names(devices: list[dict[str, Any]]) -> None:
        names = [d["name"] for d in devices]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(
                f"Duplicate device name(s) in connected_rtus: {sorted(dupes)}"
            )

    def _write_device_tree(
        self, host_dir: str, devices: list[dict[str, Any]]
    ) -> list[tuple[str, str]]:
        """Render one device resource folder per RTU, returning (src, dst) injects."""
        injects = []

        for device in devices:
            device_dir = f"{host_dir}/devices/{device['name']}"
            os.makedirs(device_dir, exist_ok=True)

            with open(f"{device_dir}/config.json", "w") as f:
                utils.mako_serve_template(
                    "dnp3-config.json.mako", TEMPLATES_DIR, f, device=device
                )
            with open(f"{device_dir}/resource.json", "w") as f:
                utils.mako_serve_template(
                    "dnp3-resource.json.mako",
                    TEMPLATES_DIR,
                    f,
                    uuid=str(uuid4()),
                    timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )

            for fname in ("config.json", "resource.json"):
                injects.append(
                    (
                        f"{device_dir}/{fname}",
                        f"{GUEST_DEVICE_DIR}/{device['name']}/{fname}",
                    )
                )

        return injects

    def _write_perspective(
        self,
        hostname: str,
        host_dir: str,
        pcfg: PerspectiveConfig,
        devices: list[dict[str, Any]],
    ) -> None:
        """Render the Perspective project and the tag-provider seed, injected
        file-by-file into the gateway's data tree."""
        build_dir = f"{host_dir}/perspective"
        project_dir = f"{build_dir}/project/{pcfg.project}"
        self._write_perspective_project(
            project_dir, pcfg.project, [d["name"] for d in devices]
        )
        self._write_tag_tree(f"{build_dir}/tags")
        for src_dir, dst_dir in (
            (project_dir, f"{GUEST_PROJECTS_DIR}/{pcfg.project}"),
            (f"{build_dir}/tags", GUEST_TAG_DIR),
        ):
            for src, dst in self._tree_injects(src_dir, dst_dir):
                self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})

    def _write_api(self, hostname: str, host_dir: str, acfg: ApiConfig) -> None:
        """Render the WebDev tag-API project and inject it file-by-file into
        the gateway's data tree. Independent of perspective and connected_rtus:
        the resource browses the OPC server live at request time."""
        project_dir = f"{host_dir}/api/project/{API_PROJECT_NAME}"
        self._write_api_project(project_dir, acfg)
        dst_dir = f"{GUEST_PROJECTS_DIR}/{API_PROJECT_NAME}"
        for src, dst in self._tree_injects(project_dir, dst_dir):
            self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})

    @staticmethod
    def _write_api_project(project_dir: str, acfg: ApiConfig) -> None:
        """Copy the WebDev project tree captured from a live 8.3 gateway, then
        patch the auth settings on the `tags` resource's POST (control) method.
        The project name is fixed and reads stay open, so this is the only
        dynamic part; WebDev stores per-method auth in the resource's
        config.json."""
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
        shutil.copytree(API_TEMPLATES_DIR, project_dir)

        config_path = (
            f"{project_dir}/com.inductiveautomation.webdev/resources/tags/config.json"
        )
        with open(config_path) as f:
            config = json.load(f)
        post = config["doPost"]
        post["require-auth"] = acfg.auth
        post["required-roles"] = ",".join(acfg.roles)
        post["user-source"] = acfg.user_source if acfg.auth else ""
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

    @staticmethod
    def _tree_injects(src_dir: str, dst_dir: str) -> list[tuple[str, str]]:
        """One inject per file: minimega creates missing parent directories
        per file, while copying a whole directory would nest wrongly if the
        destination already existed in the image."""
        injects = []
        for root, dirs, files in os.walk(src_dir):
            dirs.sort()
            rel = os.path.relpath(root, src_dir)
            prefix = dst_dir if rel == "." else f"{dst_dir}/{rel}"
            for fname in sorted(files):
                injects.append((os.path.join(root, fname), f"{prefix}/{fname}"))
        return injects

    def _write_perspective_project(
        self, project_dir: str, project: str, device_names: list[str]
    ) -> None:
        """Copy the static project tree, then patch the two dynamic files:
        the project title and the overview view's tab list (one embedded
        station view per RTU device)."""
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
        shutil.copytree(PERSPECTIVE_TEMPLATES_DIR, project_dir)

        path = f"{project_dir}/project.json"
        with open(path) as f:
            proj = json.load(f)
        proj["title"] = project
        with open(path, "w") as f:
            json.dump(proj, f, indent=2)

        path = (
            f"{project_dir}/com.inductiveautomation.perspective/views/overview"
            "/view.json"
        )
        with open(path) as f:
            view = json.load(f)
        root = view["root"]
        for i, name in enumerate(device_names, start=1):
            root["props"]["tabs"].append(name)
            root["children"].append(
                {
                    "meta": {"name": f"EmbeddedView_{i}"},
                    "position": {"tabIndex": i},
                    "props": {"params": {"rtuName": name}, "path": "station"},
                    "type": "ia.display.view",
                }
            )
        with open(path, "w") as f:
            json.dump(view, f, indent=2)

    @staticmethod
    def _write_tag_tree(tags_dir: str) -> None:
        """Seed the `[default]` provider with the tag-sync heartbeat; every
        device's points are then imported gateway-side by its event script."""
        os.makedirs(tags_dir, exist_ok=True)

        with open(TAG_FOLDER_RESOURCE_FILE) as f:
            resource = json.load(f)
        resource["files"] = ["tags.json"]

        with open(TAG_SYNC_TAG_FILE) as f:
            tag = json.load(f)
        with open(TAG_SYNC_SCRIPT_FILE) as f:
            tag["eventScripts"][0]["script"] = f.read()

        with open(f"{tags_dir}/tags.json", "w") as f:
            json.dump([tag], f, indent=2)
        with open(f"{tags_dir}/unary-resource.json", "w") as f:
            json.dump(resource, f, indent=2)

    def _configure_perspective_client(
        self, client, gateways: dict[str, PerspectiveConfig]
    ) -> None:
        hostname = client.hostname
        cfg = PerspectiveClientConfig(**client.metadata)

        if cfg.connected_gateway:
            if cfg.connected_gateway not in gateways:
                raise ValueError(
                    f"'{hostname}' connected_gateway '{cfg.connected_gateway}' "
                    "is not a perspective-enabled gateway"
                )
            gw_hostname = cfg.connected_gateway
        elif len(gateways) == 1:
            gw_hostname = next(iter(gateways))
        else:
            raise ValueError(
                f"'{hostname}' needs connected_gateway: found {len(gateways)} "
                "perspective-enabled gateways"
            )

        ip = self.extract_node_interface_ip(gw_hostname, cfg.interface)
        if not ip:
            msg = (
                f"gateway '{gw_hostname}' has no addressed interface "
                f"'{cfg.interface or '(first)'}' in the topology"
            )
            if not self.dryrun:
                raise ValueError(msg)
            logger.warning(f"Dry run: {msg}; using placeholder IP")
            ip = "127.0.0.1"

        host_dir = f"{self.app_dir}/{hostname}"
        os.makedirs(host_dir, exist_ok=True)

        url = (
            f"http://{ip}:8088/data/perspective/client/{gateways[gw_hostname].project}"
        )
        self._inject_open_client_script(hostname, host_dir, url)

    def _inject_open_client_script(
        self, hostname: str, host_dir: str, url: str
    ) -> None:
        """Startup script that opens the HMI page in a browser."""
        script = f"{host_dir}/99-ignition-perspective.ps1"
        with open(script, "w", newline="\r\n") as f:
            utils.mako_serve_template(
                "99-ignition-perspective.ps1.mako", TEMPLATES_DIR, f, url=url
            )
        self.add_inject(
            hostname=hostname, inject={"src": script, "dst": GUEST_CLIENT_SCRIPT_DST}
        )
