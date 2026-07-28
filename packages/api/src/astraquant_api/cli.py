from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from threading import Thread

import uvicorn

from astraquant_api.app import AppState, create_app
from astraquant_api.config import RuntimeConfig
from astraquant_api.data_repository import DataCatalogRepository
from astraquant_api.database import create_database, migrate_database
from astraquant_api.logging import ActivityBuffer, configure_logging
from astraquant_api.repository import TaskRepository
from astraquant_api.supervisor import TaskSupervisor

PROTOCOL_VERSION = 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="astraquant-api")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("serve")
    arguments = parser.parse_args()
    if arguments.command != "serve":
        parser.error("unsupported command")
    serve()


def serve() -> None:
    config = RuntimeConfig.from_environment()
    database_url = f"sqlite:///{config.database_path}"
    migrate_database(database_url)
    engine = create_database(database_url)
    repository = TaskRepository(engine)
    repository.interrupt_active_tasks("service_restarted")
    data_catalog = DataCatalogRepository(engine)
    data_catalog.reconcile_staged()
    activity = ActivityBuffer()
    logger = configure_logging(config.log_dir, activity)
    supervisor = TaskSupervisor(repository)
    state = AppState(
        repository=repository,
        data_catalog=data_catalog,
        supervisor=supervisor,
        activity=activity,
        session_token=config.session_token,
        state_dir=config.state_dir,
        allowed_data_instruments=config.allowed_data_instruments,
        enable_akshare=config.enable_akshare,
        shutdown_grace_seconds=config.shutdown_grace_seconds,
    )
    application = create_app(state)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((config.host, config.port))
    server_socket.listen(2048)
    bound_port = int(server_socket.getsockname()[1])

    uvicorn_config = uvicorn.Config(
        application,
        host=config.host,
        port=bound_port,
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(uvicorn_config)

    def request_server_exit() -> None:
        state.shutdown_event.wait()
        server.should_exit = True

    shutdown_monitor = Thread(
        target=request_server_exit,
        name="astraquant-shutdown-monitor",
        daemon=True,
    )
    shutdown_monitor.start()

    ready = {
        "type": "ready",
        "protocol_version": PROTOCOL_VERSION,
        "host": config.host,
        "port": bound_port,
        "pid": os.getpid(),
    }
    logger.info("runtime.ready", component="api", port=bound_port)
    print(
        json.dumps(ready, separators=(",", ":"), sort_keys=True),
        file=sys.stdout,
        flush=True,
    )
    try:
        server.run(sockets=[server_socket])
    finally:
        supervisor.shutdown(config.shutdown_grace_seconds)
        engine.dispose()


if __name__ == "__main__":
    main()
