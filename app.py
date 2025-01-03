from __future__ import annotations

import os
import yaml
import logging
from textual.app import App, ComposeResult
from textual.widgets import Button, Static, Input, Header, Footer, Label
from textual.screen import Screen
from textual.containers import Vertical, Horizontal, Container
from textual.reactive import reactive
import ast

# debug log
logging.basicConfig(
    filename="app_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="w",
)

DEFAULT_CONFIG = {
    "justicar": {
        "port": "1309",
        "configuration file": "/opt/cd2n/justicar",
        "name": "justicar",
    },
    "chain": {
        "name": "cess-chain",
        "port": "9944",
        "network": "testnet",
        "configuration file": "/opt/cd2n/chain",
    }
}


def load_config_from_docker_compose(path: str = "docker-compose.yml") -> dict:
    """
    Parse the configuration from docker-compose.yml.
    If the file does not exist or the structure does not match, DEFAULT_CONFIG is returned.
    """
    if not os.path.exists(path):
        return DEFAULT_CONFIG.copy()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        new_config = {}
        for service_name in DEFAULT_CONFIG.keys():
            service_data = data.get("services", {}).get(service_name, {})
            ports = service_data.get(
                "ports", DEFAULT_CONFIG[service_name]["port"])
            if len(ports) > 0:
                ports = ports[0].split(':')[0]

            configuration_path = service_data.get(
                "volumes", DEFAULT_CONFIG[service_name]["configuration file"])
            if len(configuration_path) > 0:
                configuration_path = configuration_path[0].split(':')[0]
            logging.debug(f"service_data is : {service_data}")
            match service_name:
                case "justicar":
                    new_config[service_name] = {
                        "port": ports,
                        "configuration file": configuration_path,
                        "name": service_data.get("container_name", DEFAULT_CONFIG[service_name]["name"]),
                    }
                case "chain":
                    network = ""
                    if service_data.get("image") is not None:
                        network = service_data.get("image").split(":")[1]
                    else:
                        network = DEFAULT_CONFIG[service_name]["network"]

                    new_config[service_name] = {
                        "port": ports,
                        "configuration file": configuration_path,
                        "name": service_data.get("container_name", DEFAULT_CONFIG[service_name]["name"]),
                        "network": network,
                    }

                case _:
                    logging.error(
                        f"[Error] no know what service it is: {service_name}")

        return new_config
    except Exception as e:
        logging.error(f"failed to load config from docker-compose.yml: {e}")
        return DEFAULT_CONFIG.copy()


def save_config_to_docker_compose(config: dict, path: str = "docker-compose.yml"):

    services = {}
    for service_name, service_config in config.items():
        match service_name:
            case "justicar":
                services[service_name] = {
                    "image": "cdn:latest",
                    "container_name": service_config["name"],
                    "devices": [
                        "/dev/sgx_enclave:/dev/sgx_enclave",
                        "/dev/sgx_provision:/dev/sgx_provision",
                    ],
                    "ports": [service_config["port"]+":1309"],
                    "volumes": [
                        service_config["configuration file"] +
                        ":/opt/justicar/backups"
                    ],
                    "networks": ["cd2n"],
                    "stdin_open": True,
                    "tty": True,
                }
            case "chain":
                services[service_name] = {
                    "image": "cesslab/cess-chain:"+service_config["network"],
                    "volumes": [
                        service_config["configuration file"] +
                        ":/opt/cess/data"
                    ],
                    "command": [
                        "--base-path",
                        "/opt/cess/data",
                        "--chain",
                        "cess-"+service_config["network"],
                        "--port",
                        "30336",
                        "--name",
                        "cess",
                        "--rpc-port",
                        "9944",
                        "--execution",
                        "WASM",
                        "--wasm-execution",
                        "compiled",
                        "--in-peers",
                        "75",
                        "--out-peers",
                        "75",
                        "--rpc-max-response-size",
                        "32",
                        "--pruning",
                        "archive",
                        "--rpc-external",
                        "--rpc-methods",
                        "unsafe",
                        "--rpc-cors",
                        "all"
                    ],
                    "logging": {
                        "driver": "json-file",
                        "options": {
                            "max-size": "300m",
                            "max-file": "10",
                        }
                    },
                    "networks": ["cd2n"],
                    "container_name": service_config["name"],
                    "ports": [service_config["port"]+":9944", "30336:30336"],
                }
            case _:
                logging.error(f"[Error] no support service: {service_name}")

    docker_compose_data = {
        "version": "3.9",
        "services": services,
        "networks": {
            "cd2n": {
                "name": "cd2n",
                "driver": "bridge",
            }
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(docker_compose_data, f, sort_keys=False)

    logging.debug(f"docker-compose.yml already save in: {path}")


class ConfigScreen(Screen):
    """
    Configuration details page.
    """
    BINDINGS = [
        ("escape", "go_back", "Go Back To Main Menu"),
        ("ctrl+s", "save_config", "Save Config and Return"),
    ]

    def __init__(self, service_name: str, config: dict, **kwargs):
        super().__init__(**kwargs)
        self.service_name = service_name
        # current service configuration
        self.current_config = config[service_name].copy()
        self.input_fields = {}

    def compose(self) -> ComposeResult:
        # yield Header()

        # Display and edit configuration items
        with Vertical(id="setting-container"):
            with Container(id="setting-title-container"):
                yield Static(f"Configuration for: {self.service_name}", classes="setting-title")
            with Container(id="setting-items-container"):
                for key, value in self.current_config.items():
                    yield Label(f"{key.capitalize()}:")
                    input_field = Input(value=str(value))
                    self.input_fields[key] = input_field
                    yield input_field

            with Horizontal(id="save-cancel-container"):
                yield Button("Save and Return", id="save_and_back", variant="primary")
                yield Button("Cancel", id="cancel", variant="error")

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_and_back":
            self.action_save_config()
        elif event.button.id == "cancel":
            self.action_go_back()

    def action_go_back(self) -> None:
        """
        button or ESC to return to the main menu.
        """
        self.app.pop_screen()

    def action_save_config(self) -> None:
        """
        Save the configuration of the current page and return to the main menu.
        """
        for key, input_field in self.input_fields.items():
            self.current_config[key] = input_field.value

        # Update to the app's global config
        self.app.config[self.service_name] = self.current_config
        save_config_to_docker_compose(self.app.config)
        self.app.pop_screen()


class MainMenu(Screen):
    """
    Main menu page.
    """
    BINDINGS = [
        ("^q", "quit", "Exit"),
    ]

    def compose(self) -> ComposeResult:
        # yield Header()
        with Vertical(id="main-menu-container"):
            with Container(id="main-menu-title-container"):
                yield Static("CD2N Main Menu", classes="title")

            with Container(id="settings-list"):
                for service_name in self.app.config.keys():
                    yield Button(f"{service_name.capitalize()} Configure", id=f"{service_name}_btn")

            with Container(id="run_compose-container"):
                yield Button("Run CD2N Right Now!", id="run_compose", variant="primary")

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id.endswith("_btn"):
            service_name = button_id[:-4]  # cut off "_btn" part
            self.app.push_screen(ConfigScreen(service_name, self.app.config))
        elif button_id == "run_compose":
            save_config_to_docker_compose(self.app.config)
            logging.debug(f"create docker compose and run")


class CD2N(App):
    CSS_PATH = "app.tcss"
    config = reactive({})  # global configuration

    def on_mount(self) -> None:
        """
        When the application starts, read the configuration from docker-compose.yml to self.config.
        """
        self.config = load_config_from_docker_compose()

    def on_ready(self) -> None:
        """
        Enter the main menu when the application is ready.
        """
        self.push_screen(MainMenu())


if __name__ == "__main__":
    CD2N().run()