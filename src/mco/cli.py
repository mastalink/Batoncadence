"""
BatonCadence Typer CLI & Setup Wizard
===================================
Provides user onboarding, credentials encryption, FastAPI serving,
and background daemon listener.
"""

from __future__ import annotations

import os
import sys
import asyncio
import secrets
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mco.cli")


import typer
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

from mco.config import get_config, EnvironmentProfile, SENSITIVE_KEYS
from mco.security import get_secret_store, WindowsCredentialProvider, PasswordKeyProvider
from mco.orchestrator.routes import router as jobs_router, agents_router, register_broadcast_callback
from mco.orchestrator.listener import AgentListener
from mco.notifiers.ntfy import notify, notify_agent_online, notify_agent_offline, get_ntfy_config, notify_gateway_startup

# Initialize typer app and console
app = typer.Typer(help="BatonCadence: Multi-Client Agent Orchestrator.")
console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# 1. Onboarding Setup Wizard
# ─────────────────────────────────────────────────────────────────────────────
@app.command("setup")
def setup_wizard():
    """Run the interactive onboarding and environment installer wizard."""
    console.print(Panel.fit(
        "[bold cyan]BatonCadence Standalone Setup Wizard[/bold cyan]\n"
        "Configure your agent profile, credentials, and military-grade encryption.",
        border_style="cyan"
    ))

    config = get_config()
    
    # 1. Operator Info
    operator_name = Prompt.ask("Enter Operator Name", default="Operator")
    config.set("OPERATOR_NAME", operator_name)

    # 2. Environment Profile Selection
    console.print("\n[bold yellow]Step 1: Select Environment Profile[/bold yellow]")
    console.print("  [1] Local-Only  - Run tools and LLMs locally (e.g. Ollama). No database needed.")
    console.print("  [2] Cloud-Heavy - Connect to cloud-hosted databases (Supabase) and proprietary LLM APIs.")
    console.print("  [3] Hybrid      - Connect to both local tools and cloud integrations.")
    
    profile_choice = Prompt.ask(
        "Choose profile",
        choices=["1", "2", "3"],
        default="3"
    )
    
    profile_map = {
        "1": EnvironmentProfile.LOCAL_ONLY,
        "2": EnvironmentProfile.CLOUD_HEAVY,
        "3": EnvironmentProfile.HYBRID
    }
    selected_profile = profile_map[profile_choice]
    config.set("MCO_PROFILE", selected_profile)
    console.print(f"[OK] Profile configured as [bold green]{selected_profile}[/bold green].")

    # 3. Suppress or prompt Supabase if cloud is included
    supabase_url = ""
    supabase_key = ""
    if selected_profile in (EnvironmentProfile.CLOUD_HEAVY, EnvironmentProfile.HYBRID):
        console.print("\n[bold yellow]Step 2: Database Configuration (Supabase)[/bold yellow]")
        url_def = config.get("SUPABASE_URL") or ""
        if url_def == "encrypted_in_secret_store":
            url_def = ""
        key_def = config.get("SUPABASE_KEY") or ""
        if key_def == "encrypted_in_secret_store":
            key_def = ""

        supabase_url = Prompt.ask("Enter Supabase URL", default=url_def)
        supabase_key = Prompt.ask("Enter Supabase Key (anon/service)", default=key_def)
        
        # Save temporary plain values; we will encrypt them below if requested
        config.set("SUPABASE_URL", supabase_url)
        config.set("SUPABASE_KEY", supabase_key)

    # 4. Encryption Prompt (AES-256-GCM Secure Store)
    console.print("\n[bold yellow]Step 3: Configuration Encryption (AES-256-GCM)[/bold yellow]")
    encrypt_creds = Confirm.ask("Do you want to encrypt sensitive credentials and API keys in the MCO Secret Store?", default=True)

    if encrypt_creds:
        store = get_secret_store()
        if store.is_initialized():
            console.print("[warning]An existing secret store was found. Re-keying existing store...[/warning]")
            # Attempt to unlock first
            if not store.auto_unlock():
                pw = Prompt.ask("Enter current master password to unlock and overwrite", password=True)
                envelope = Path(store._path).read_text(encoding="utf-8")
                import json, base64
                env_dict = json.loads(envelope)
                salt = base64.b64decode(env_dict["salt"])
                iterations = env_dict.get("iterations", 600000)
                cur_key = store.derive_key(pw, salt, iterations)
                if not store.unlock(cur_key):
                    console.print("[yellow][WARNING] Incorrect password.[/yellow]")
                    overwrite = Confirm.ask("Would you like to delete the existing secret store and start fresh?", default=False)
                    if overwrite:
                        try:
                            Path(store._path).unlink(missing_ok=True)
                            store._secrets = None
                            store._master_key = None
                            
                            # Fresh Master Password configuration
                            use_pw = Confirm.ask("Would you like to set a master password to protect your secrets?", default=True)
                            master_key = None
                            salt = None
                            if use_pw:
                                master_pw = Prompt.ask("Enter a strong master password", password=True)
                                salt = os.urandom(32)
                                master_key = store.derive_key(master_pw, salt)
                            else:
                                master_key = secrets.token_bytes(32)
                                console.print("✓ Generated a secure random master key.")
                            store.initialize(master_key, salt=salt)
                        except Exception as e:
                            console.print(f"[red][ERROR] Failed to reset secret store: {e}[/red]")
                            return
                    else:
                        console.print("[red][ERROR] Incorrect password. Aborting encryption setup.[/red]")
                        return
        else:
            # Fresh Master Password configuration
            use_pw = Confirm.ask("Would you like to set a master password to protect your secrets?", default=True)
            master_key = None
            salt = None
            if use_pw:
                master_pw = Prompt.ask("Enter a strong master password", password=True)
                # Derive 32-byte key
                salt = os.urandom(32)
                master_key = store.derive_key(master_pw, salt)
            else:
                # Generate a random master key
                master_key = secrets.token_bytes(32)
                console.print("✓ Generated a secure random master key.")

            # Initialize the store
            store.initialize(master_key, salt=salt)

        # Securely migrate values to secret store
        store_unlocked = store.is_unlocked
        if store_unlocked:
            # Encrypt the freshly-collected values directly. Do NOT read these back via
            # config.get(key): for sensitive keys it resolves store-first and would echo
            # a stale/sentinel value instead of what the user just entered.
            collected = {"SUPABASE_URL": supabase_url, "SUPABASE_KEY": supabase_key}
            for key in SENSITIVE_KEYS:
                val = collected.get(key) or config.get(key)
                if val and val != "encrypted_in_secret_store":
                    config.set(key, val, encrypt=True)

            # Store in Windows Credential Manager ifNT
            if os.name == "nt" and store._master_key:
                save_to_cred_mgr = Confirm.ask(
                    "Would you like to store the master unlock key in Windows Credential Manager?\n"
                    "This enables automatic, passwordless config unlocking upon reboots/runs.",
                    default=True
                )
                if save_to_cred_mgr:
                    try:
                        WindowsCredentialProvider.store_key(store._master_key)
                        console.print("[OK] Successfully stored master key in Windows Credential Manager.")
                    except Exception as e:
                        console.print(f"[red][ERROR] Failed to save to Windows Credential Manager: {e}[/red]")
            
            console.print("[OK] Secrets successfully migrated and encrypted.")
        else:
            console.print("[red][ERROR] Secret store initialized but locked. Secrets migration skipped.[/red]")
    else:
        console.print("[yellow]Plaintext environment configuration chosen. Secrets are saved in standard .env[/yellow]")

    console.print("\n[bold green][OK] BatonCadence Onboarding & Installation Complete![/bold green]")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Serve Command (FastAPI HTTP + WebSocket server)
# ─────────────────────────────────────────────────────────────────────────────
class ConnectionManager:
    """Manages active WebSocket subscription channels."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


ws_manager = ConnectionManager()


async def server_broadcast_callback(event: str, job: dict) -> None:
    """Callback triggered by REST router updates to notify WebSocket clients."""
    payload = {
        "type": "event",
        "payload": {
            "event": event,
            "job": job
        }
    }
    await ws_manager.broadcast(payload)

def create_app() -> FastAPI:
    """Create and configure the FastAPI application server."""
    app_server = FastAPI(
        title="BatonCadence Gateway Server",
        description="FastAPI WebSocket and REST Hub for Agent Job Coordination."
    )

    # Mount REST routing
    app_server.include_router(jobs_router)
    app_server.include_router(agents_router)

    # Enterprise integrations (ServiceNow, Dynatrace, webhooks)
    from mco.orchestrator.integration_routes import integrations_router
    app_server.include_router(integrations_router)

    # Mythos shared context (collective agent memory)
    from mco.orchestrator.context_routes import context_router
    app_server.include_router(context_router)

    # Unauthenticated liveness/readiness probe for cloud load balancers and
    # orchestrators (K8s, ECS, Cloud Run). Reports DB wiring, never secrets.
    @app_server.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        from mco.orchestrator.routes import get_db_client, kill_switch_active
        client = get_db_client()
        return {
            "status": "ok",
            "database": client is not None,
            "backend": getattr(client, "backend", "supabase") if client is not None else None,
            "paused": kill_switch_active(),
        }

    # Control-plane dashboard (static single page; auth happens via the API token)
    from fastapi.responses import HTMLResponse
    from mco.dashboard import DASHBOARD_HTML

    @app_server.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> str:
        return DASHBOARD_HTML

    # BatonCadence Console (full control-plane GUI; auth via API bearer token)
    from mco.console import get_console_html

    @app_server.get("/console", response_class=HTMLResponse, include_in_schema=False)
    async def console_ui() -> str:
        return get_console_html()

    # Register broadcast callback
    register_broadcast_callback(server_broadcast_callback)

    # WebSocket Broadcast route
    @app_server.websocket("/ws/broadcast")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        
        # Wait up to 5 seconds for authentication frame
        authenticated = False
        authenticated_instance_id = None
        
        from mco.orchestrator.routes import get_db_client
        db_client = get_db_client()
        
        if not db_client:
            # If DB is not configured, bypass authentication with a warning (local-only compatibility)
            logger.warning("Database not configured. Bypassing WebSocket authentication for incoming connection.")
            authenticated = True
            ws_manager.active_connections.append(websocket)
        else:
            try:
                # 1. Read first message (should be authenticate)
                auth_data_str = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                auth_msg = json.loads(auth_data_str)
                msg_type = auth_msg.get("type")
                payload = auth_msg.get("payload") or {}
                
                if msg_type == "authenticate":
                    instance_id = payload.get("instance_id")
                    role = payload.get("role")
                    token = payload.get("token")
                    
                    if instance_id and role and token:
                        # Calculate SHA-256 hash of token
                        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
                        
                        # Verify in DB
                        res = db_client.table("agent_registry")\
                            .select("*")\
                            .eq("instance_id", instance_id)\
                            .eq("auth_token_hash", token_hash)\
                            .execute()
                        
                        if res.data:
                            authenticated = True
                            authenticated_instance_id = instance_id
                            
                            # Update status to online in database
                            from datetime import datetime, timezone
                            db_client.table("agent_registry").update({
                                "status": "online",
                                "last_seen_at": datetime.now(timezone.utc).isoformat()
                            }).eq("instance_id", instance_id).execute()
                            
                            # Register in ws_manager for broadcast receiving
                            ws_manager.active_connections.append(websocket)
                            
                            # Send success frame
                            await websocket.send_json({
                                "type": "authenticated",
                                "payload": {"success": True}
                            })
                            logger.info(f"Agent '{instance_id}' ({role}) successfully authenticated.")
                            
                            # NTFY addon: notify agent online
                            try:
                                notify_agent_online(role, instance_id)
                            except Exception:
                                pass
                        
                if not authenticated:
                    await websocket.send_json({
                        "type": "authenticated",
                        "payload": {"success": False, "error": "Authentication failed"}
                    })
                    await websocket.close()
                    return
                    
            except asyncio.TimeoutError:
                logger.warning("WebSocket authentication timeout (no authentication frame received in 5s).")
                try:
                    await websocket.close()
                except Exception:
                    pass
                return
            except Exception as e:
                logger.error(f"WebSocket authentication error: {e}")
                try:
                    await websocket.close()
                except Exception:
                    pass
                return

        # 2. Main message loop for authenticated socket
        try:
            while True:
                data = await websocket.receive_text()
                # Parse in-flight messages (like acknowledgements, job updates)
                try:
                    msg = json.loads(data)
                    msg_type = msg.get("type")
                    payload = msg.get("payload") or {}

                    if msg_type == "job_update":
                        # Forward/broadcast the update to all connected agents
                        task_id = payload.get("task_id")
                        status = payload.get("status")
                        if task_id and status:
                            await ws_manager.broadcast({
                                "type": "event",
                                "payload": {
                                    "event": "job_pending" if status == "pending" else "job_updated",
                                    "job": {"id": task_id, "status": status, **payload}
                                }
                            })
                except Exception:
                    pass
        except WebSocketDisconnect:
            if websocket in ws_manager.active_connections:
                ws_manager.disconnect(websocket)
            
            # Set agent to offline on disconnect + ntfy notification
            if authenticated_instance_id and db_client:
                try:
                    db_client.table("agent_registry").update({
                        "status": "offline"
                    }).eq("instance_id", authenticated_instance_id).execute()
                    logger.info(f"Agent '{authenticated_instance_id}' disconnected, set to offline.")
                    
                    # NTFY addon: notify agent offline
                    try:
                        # We don't have the role easily here, so use a generic notification
                        notify_agent_offline("unknown", authenticated_instance_id)
                    except Exception:
                        pass
                except Exception as db_err:
                    logger.warning(f"Failed to set agent offline: {db_err}")

    return app_server


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="The host to bind to."),
    port: int = typer.Option(18789, help="The port to bind to.")
):
    """Start the BatonCadence FastAPI WebSocket/REST API Server."""
    console.print(Panel.fit(
        f"[bold green]Starting BatonCadence Server[/bold green]\n"
        f"Host: http://{host}:{port}\n"
        f"Console: http://{host}:{port}/console\n"
        f"WebSocket: ws://{host}:{port}/ws/broadcast",
        border_style="green"
    ))

    # Trigger dynamic decrypt/load
    config = get_config()

    app_server = create_app()

    # Pre-warm the (now memoized) Supabase client so the first request isn't slow.
    from mco.orchestrator.routes import get_db_client
    if get_db_client() is not None:
        console.print("[dim]Supabase client pre-warmed.[/dim]")

    # Initialize ntfy webhook addon if env vars are present
    ntfy_cfg = get_ntfy_config()
    if ntfy_cfg.get("server") and ntfy_cfg.get("topic"):
        try:
            # Gather rich stats for the startup notification
            stats = {
                "host": host,
                "port": port,
                "pid": os.getpid(),
            }

            db_client = get_db_client()
            if db_client:
                try:
                    agents_res = db_client.table("agent_registry").select("status").execute()
                    stats["agent_count"] = len(agents_res.data or [])
                    stats["online_count"] = sum(1 for a in (agents_res.data or []) if a.get("status") == "online")

                    jobs_res = db_client.table("agent_jobs").select("id").eq("status", "pending").execute()
                    stats["pending_jobs"] = len(jobs_res.data or [])
                except Exception:
                    pass

            # Light process info to help detect leaks (mco.exe, node, git, etc.)
            try:
                import psutil
                stats["process_count"] = len(psutil.pids())
            except Exception:
                pass

            notify_gateway_startup(stats)
            console.print(f"[dim]NTFY notifier enabled -> {ntfy_cfg['server']}/{ntfy_cfg['topic']}[/dim]")
        except Exception as ntfy_err:
            console.print(f"[yellow]NTFY notifier init warning: {ntfy_err}[/yellow]")

    # Launch Uvicorn
    # Start background process snapshot reporter (helps catch mco.exe / codex / git / node leaks)
    def _periodic_process_snapshot():
        import threading
        import time
        ntfy_cfg = get_ntfy_config()
        if not (ntfy_cfg.get("server") and ntfy_cfg.get("topic")):
            return
        def _reporter():
            while True:
                try:
                    import psutil
                    snapshot = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "total_processes": len(psutil.pids()),
                        "mco_processes": len([p for p in psutil.process_iter(['name']) if 'mco' in (p.info['name'] or '').lower()]),
                        "node_processes": len([p for p in psutil.process_iter(['name']) if 'node' in (p.info['name'] or '').lower()]),
                        "git_processes": len([p for p in psutil.process_iter(['name']) if 'git' in (p.info['name'] or '').lower()]),
                    }
                    notify(
                        json.dumps(snapshot, indent=2),
                        title="BatonCadence Process Snapshot",
                        priority=1,
                        tags=["mco", "process-snapshot", "leak-detection"],
                    )
                except Exception:
                    pass
                time.sleep(600)  # every 10 minutes
        threading.Thread(target=_reporter, daemon=True).start()

    _periodic_process_snapshot()

    # Background enterprise connector sync (opt-in via MCO_SYNC_INTERVAL seconds).
    # Pulls open ServiceNow incidents / Dynatrace problems onto the job board.
    def _periodic_connector_sync():
        import threading
        import time
        try:
            interval = float(config.get("MCO_SYNC_INTERVAL") or 0)
        except (TypeError, ValueError):
            interval = 0
        if interval <= 0:
            return
        from mco.connectors import build_connectors
        from mco.connectors.sync import sync_connector
        connectors = build_connectors()
        if not connectors:
            return
        console.print(f"[dim]Connector sync enabled every {interval:.0f}s: "
                      f"{', '.join(c.name for c in connectors)}[/dim]")

        def _syncer():
            from mco.orchestrator.routes import get_db_client
            while True:
                time.sleep(interval)
                db = get_db_client()
                if not db:
                    continue
                for conn in connectors:
                    try:
                        sync_connector(db, conn)
                    except Exception as sync_err:
                        logger.warning(f"Background sync failed for {conn.name}: {sync_err}")
        threading.Thread(target=_syncer, daemon=True).start()

    _periodic_connector_sync()

    uvicorn.run(app_server, host=host, port=port)



# ─────────────────────────────────────────────────────────────────────────────
# 2b. MCP Server (for IDE/agent GUI integration)
# ─────────────────────────────────────────────────────────────────────────────
@app.command("mcp")
def mcp_serve():
    """Run the MCO dropbox as an MCP stdio server (for Claude/Codex/Antigravity)."""
    # stdio is the MCP transport channel: do NOT write to stdout in this command.
    from mco.mcp_server import run
    run()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Background Listener Daemon
# ─────────────────────────────────────────────────────────────────────────────
@app.command("listen")
def listen(
    role: str = typer.Option("codex", help="Agent execution role (e.g. codex, script)."),
    instance: str = typer.Option("default_agent", help="Unique ID of this client listener instance."),
    config_file: str = typer.Option("agent_config.json", help="Path to local worker config file.")
):
    """Spawn the background daemon client that polls and executes Job Board tasks."""
    console.print(Panel.fit(
        f"[bold blue]Spawning BatonCadence Background Daemon[/bold blue]\n"
        f"Role: [green]{role}[/green]\n"
        f"Instance ID: [green]{instance}[/green]",
        border_style="blue"
    ))

    # Bootstrap client listener config overrides
    os.environ["AGENT_ROLE"] = role
    os.environ["AGENT_INSTANCE_ID"] = instance

    # Wire real CLI executors so leased jobs actually run (instead of mock-completing).
    try:
        from mco.orchestrator.executors import register_default_executors
        registered = register_default_executors()
        console.print(f"[dim]Registered executors for roles: {', '.join(registered)}[/dim]")
    except Exception as e:
        console.print(f"[yellow][WARN] Could not register default executors: {e}[/yellow]")

    # Connector roles: a listener for role "servicenow"/"dynatrace" executes
    # platform actions (input_payload.action) instead of running a CLI tool.
    try:
        from mco.connectors import get_connector, make_connector_executor
        from mco.orchestrator.listener import register_executor
        conn = get_connector(role)
        if conn:
            register_executor(role, make_connector_executor(conn))
            console.print(f"[dim]Role '{role}' wired to the {conn.name} connector "
                          f"(actions: {', '.join(conn.actions())}).[/dim]")
    except Exception as e:
        console.print(f"[yellow][WARN] Connector executor not wired: {e}[/yellow]")

    try:
        listener = AgentListener(config_path=config_file)
        asyncio.run(listener.start())
    except KeyboardInterrupt:
        console.print("[yellow]Background listener shut down by user.[/yellow]")
    except Exception as e:
        console.print(f"[red][ERROR] Critical error in listener daemon: {e}[/red]")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Status and Diagnostics
# ─────────────────────────────────────────────────────────────────────────────
@app.command("status")
def status():
    """Print BatonCadence health check and diagnostics."""
    config = get_config()
    store = get_secret_store()

    console.print("[bold cyan]=== BatonCadence Status Diagnostics ===[/bold cyan]\n")

    # 1. Store state
    store_init = store.is_initialized()
    store_unlocked = store.is_unlocked
    
    store_status_str = "[green]Active / Unlocked[/green]" if store_unlocked else (
        "[yellow]Active / Locked[/yellow]" if store_init else "[white]Not Configured (Plaintext Mode)[/white]"
    )
    
    console.print(f"Encryption Secure Store Path: [bold]{store._path}[/bold]")
    console.print(f"Secure Store Status: {store_status_str}\n")

    # 2. Profile configuration
    profile = config.get("MCO_PROFILE") or "Not Configured"
    console.print(f"Active Environment Profile: [bold green]{profile}[/bold green]\n")

    # 3. Settings table
    table = Table(title="Resolved Configuration Properties", show_header=True, header_style="bold magenta")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    
    masked = config.get_masked_config()
    for k, v in masked.items():
        table.add_row(k, v)
        
    console.print(table)


@app.command("register")
def register_agent(
    name: str = typer.Option(..., "--name", help="Unique name (instance ID) of the agent."),
    role: str = typer.Option(..., "--role", help="Target role of the agent (e.g. antigravity, codex)."),
    org: str = typer.Option("default", "--org", help="Tenant org the agent belongs to (multi-tenant installs).")
):
    """Register a new client agent, generating a secure access token."""
    console.print(f"[bold cyan]Registering new MCO agent...[/bold cyan]")
    
    from mco.orchestrator.routes import get_db_client
    db_client = get_db_client()
    if not db_client:
        console.print("[red][ERROR] Database not configured. Please run 'mco setup' first.[/red]")
        raise typer.Exit(code=1)
        
    token = "mco_tok_" + secrets.token_hex(24)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    
    try:
        data = {
            "instance_id": name,
            "role": role,
            "status": "offline",
            "auth_token_hash": token_hash
        }
        if org and org != "default":
            data["org_id"] = org
        res = db_client.table("agent_registry").upsert(data).execute()
        if res.data:
            console.print(Panel.fit(
                f"[bold green][OK] Agent '{name}' registered successfully![/bold green]\n\n"
                f"Role: [cyan]{role}[/cyan]\n"
                f"Status: [yellow]offline[/yellow]\n\n"
                f"[bold yellow]Save this Access Token securely. It will not be shown again:[/bold yellow]\n"
                f"[bold white]{token}[/bold white]",
                border_style="green"
            ))
        else:
            console.print("[red][ERROR] Database failed to return data on upsert.[/red]")
    except Exception as e:
        console.print(f"[red][ERROR] Failed to register agent in database: {e}[/red]")


@app.command("agents")
def list_agents():
    """List all registered agents and their current online presence status."""
    console.print("[bold cyan]=== BatonCadence Registered Agents ===[/bold cyan]\n")
    
    from mco.orchestrator.routes import get_db_client
    db_client = get_db_client()
    if not db_client:
        console.print("[red][ERROR] Database not configured. Please run 'mco setup' first.[/red]")
        raise typer.Exit(code=1)
        
    try:
        res = db_client.table("agent_registry").select("*").order("instance_id").execute()
        agents = res.data or []
        
        if not agents:
            console.print("[yellow]No agents registered. Use 'mco register' to onboard an agent.[/yellow]")
            return
            
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Agent ID (Instance ID)", style="cyan")
        table.add_column("Role", style="green")
        table.add_column("Status", style="bold")
        table.add_column("Last Seen At", style="white")
        
        for agent in agents:
            status = agent.get("status", "offline")
            status_style = "[green]online[/green]" if status == "online" else "[red]offline[/red]"
            
            table.add_row(
                agent.get("instance_id", ""),
                agent.get("role", ""),
                status_style,
                agent.get("last_seen_at", "")
            )
            
        console.print(table)
    except Exception as e:
        console.print(f"[red][ERROR] Failed to query agent registry: {e}[/red]")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Governance: workflows, audit trail, approval gates
# ─────────────────────────────────────────────────────────────────────────────
def _gateway_client():
    """GatewayClient resolved from the full config stack, not just os.environ.

    Reads MCO_GATEWAY_URL / MCO_AGENT_TOKEN / AGENT_ROLE / AGENT_INSTANCE_ID
    from get_config() (which layers .env + the AES-256-GCM secret store over
    the OS environment), so `mco workflow|approve|sync|...` work from any shell
    once the token is in .env or the vault - no per-shell `set` required.
    """
    from mco.orchestrator.client import GatewayClient
    config = get_config()
    return GatewayClient(
        base_url=config.get("MCO_GATEWAY_URL") or None,
        token=config.get("MCO_AGENT_TOKEN") or None,
        role=config.get("AGENT_ROLE") or None,
        instance_id=config.get("AGENT_INSTANCE_ID") or None,
    )


@app.command("workflow")
def run_workflow(
    file: str = typer.Argument(..., help="Path to a workflow YAML file."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and print the plan without submitting."),
):
    """Submit a declarative YAML workflow (DAG of jobs) to the Job Board."""
    from mco.orchestrator.workflows import load_workflow, topo_order, submit_workflow, WorkflowError

    try:
        workflow = load_workflow(file)
    except WorkflowError as e:
        console.print(f"[red][ERROR] Invalid workflow: {e}[/red]")
        raise typer.Exit(code=1)

    ordered = topo_order(workflow["steps"])
    console.print(f"[bold cyan]Workflow:[/bold cyan] {workflow['name']} ({len(ordered)} steps)")
    for step in ordered:
        gates = []
        if step.get("requires_approval"):
            gates.append("approval-gated")
        if step.get("max_retries"):
            gates.append(f"retries={step['max_retries']}")
        if step.get("escalate_to_role"):
            gates.append(f"escalates->{step['escalate_to_role']}")
        deps = ", ".join(step.get("depends_on") or []) or "-"
        console.print(f"  - {step['id']} [green]({step['role']})[/green] deps: {deps} {' '.join(gates)}")

    if dry_run:
        console.print("[yellow]Dry run: nothing submitted.[/yellow]")
        return

    try:
        job_ids = submit_workflow(_gateway_client(), workflow)
    except WorkflowError as e:
        console.print(f"[red][ERROR] {e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red][ERROR] Failed to submit workflow: {e}[/red]")
        raise typer.Exit(code=1)

    console.print("[bold green][OK] Workflow submitted.[/bold green]")
    for step_id, job_id in job_ids.items():
        console.print(f"  {step_id} -> {job_id}")


@app.command("audit")
def audit_trail(job_id: str = typer.Argument(..., help="Job ID to inspect.")):
    """Print a job's immutable audit trail (oldest event first)."""
    try:
        events = _gateway_client().events(job_id)
    except Exception as e:
        console.print(f"[red][ERROR] Failed to fetch audit trail: {e}[/red]")
        raise typer.Exit(code=1)

    if not events:
        console.print("[yellow]No audit events found for this job.[/yellow]")
        return

    table = Table(title=f"Audit Trail: {job_id}", show_header=True, header_style="bold magenta")
    table.add_column("Time", style="white")
    table.add_column("Event", style="cyan")
    table.add_column("Actor", style="green")
    table.add_column("Detail", style="dim")
    for ev in events:
        actor = ev.get("actor_id") or "-"
        if ev.get("actor_role"):
            actor = f"{actor} ({ev['actor_role']})"
        table.add_row(
            str(ev.get("created_at", "")),
            str(ev.get("event", "")),
            actor,
            json.dumps(ev.get("detail") or {}),
        )
    console.print(table)


@app.command("approve")
def approve(job_id: str = typer.Argument(..., help="Job ID awaiting approval.")):
    """Approve a job paused at the human-in-the-loop gate."""
    try:
        res = _gateway_client().approve(job_id)
        console.print(f"[bold green][OK] Job {job_id} approved -> {res['job']['status']}[/bold green]")
    except Exception as e:
        console.print(f"[red][ERROR] Approval failed: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("reject")
def reject(
    job_id: str = typer.Argument(..., help="Job ID awaiting approval."),
    reason: str = typer.Option("", "--reason", help="Why the job was rejected."),
):
    """Reject a job paused at the human-in-the-loop gate (terminal)."""
    try:
        res = _gateway_client().reject(job_id, reason)
        console.print(f"[bold yellow][OK] Job {job_id} rejected -> {res['job']['status']}[/bold yellow]")
    except Exception as e:
        console.print(f"[red][ERROR] Rejection failed: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("retry")
def retry(job_id: str = typer.Argument(..., help="Failed/rejected job ID to re-queue.")):
    """Re-queue a failed or rejected job back to pending (approver-role token)."""
    try:
        res = _gateway_client().retry(job_id)
        console.print(f"[bold green][OK] Job {job_id} re-queued -> {res['job']['status']}[/bold green]")
    except Exception as e:
        console.print(f"[red][ERROR] Retry failed: {e}[/red]")
        raise typer.Exit(code=1)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Enterprise integrations
# ─────────────────────────────────────────────────────────────────────────────
@app.command("connectors")
def list_connectors_cmd():
    """List configured enterprise connectors and their health (via the gateway)."""
    try:
        rows = _gateway_client().integrations()
    except Exception as e:
        console.print(f"[red][ERROR] Failed to query integrations: {e}[/red]")
        raise typer.Exit(code=1)

    if not rows:
        console.print("[yellow]No connectors configured. Set SERVICENOW_INSTANCE_URL / "
                      "DYNATRACE_BASE_URL (plus credentials) and restart the gateway.[/yellow]")
        return

    table = Table(title="Enterprise Connectors", show_header=True, header_style="bold magenta")
    table.add_column("Connector", style="cyan")
    table.add_column("Health", style="bold")
    table.add_column("Actions", style="dim")
    for row in rows:
        health = row.get("health") or {}
        status = "[green]ok[/green]" if health.get("ok") else f"[red]down[/red] {health.get('detail', '')}"
        table.add_row(row.get("name", ""), status, ", ".join(row.get("actions") or []))
    console.print(table)


@app.command("sync")
def sync_cmd(connector: str = typer.Argument(..., help="Connector name (servicenow, dynatrace).")):
    """Pull open platform objects (incidents/problems) onto the job board."""
    try:
        summary = _gateway_client().sync_connector(connector)
    except Exception as e:
        console.print(f"[red][ERROR] Sync failed: {e}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold green][OK] {connector} sync:[/bold green] "
                  f"pulled={summary.get('pulled')} created={len(summary.get('created') or [])} "
                  f"skipped={summary.get('skipped')} (already on the board)")


@app.command("platform")
def platform_action(
    connector: str = typer.Argument(..., help="Connector name (servicenow, dynatrace)."),
    action: str = typer.Argument(..., help="Action name (see 'mco connectors')."),
    params: str = typer.Option("{}", "--params", help="JSON parameters for the action."),
):
    """Run a connector control action directly (requires an approver-role token)."""
    try:
        parsed = json.loads(params)
    except json.JSONDecodeError as e:
        console.print(f"[red][ERROR] --params is not valid JSON: {e}[/red]")
        raise typer.Exit(code=1)
    try:
        res = _gateway_client().platform_action(connector, action, parsed)
        console.print(f"[bold green][OK][/bold green] {json.dumps(res.get('result'), indent=2)}")
    except Exception as e:
        console.print(f"[red][ERROR] Action failed: {e}[/red]")
        raise typer.Exit(code=1)


def main():
    app()


if __name__ == "__main__":
    main()
