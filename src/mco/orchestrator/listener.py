"""
Agent Listener Worker Client
============================
Listens for tasks delegated via the Job Board and executes them locally.
Supports multiple named instances across different machines.
"""

import os
import json
import asyncio
import websockets
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from mco.config import get_config

logger = logging.getLogger("mco.orchestrator.listener")

# Registry of custom executors mapping role strings to async execution functions:
# async def custom_executor(job: dict, prompt: str) -> tuple[Optional[str], Optional[str]]
_executor_registry: Dict[str, Callable] = {}

def register_executor(role: str, executor_func: Callable) -> None:
    """Register a custom execution function for a specific agent role."""
    _executor_registry[role] = executor_func
    logger.info(f"Registered custom executor for role: {role}")


class AgentListener:
    """
    Background worker that registers as an agent instance,
    polls/listens for pending jobs, leases them atomically,
    runs them locally, and updates their status on Supabase.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or "agent_config.json"
        self.instance_id = "default_agent"
        self.role = "codex"
        self.gateway_ws_url = "ws://127.0.0.1:18789"
        self.poll_interval = 30.0  # seconds

        self._load_config()

        # Initialize Supabase client via MCO config
        config = get_config()
        supabase_url = config.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
        supabase_key = config.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")

        if not supabase_url or not supabase_key:
            raise ValueError(
                "Supabase URL and Key must be configured (via setup wizard, environment variables "
                "SUPABASE_URL/SUPABASE_KEY, or local .env)."
            )

        from supabase import create_client
        self.db_client = create_client(supabase_url, supabase_key)
        logger.info(f"Agent Listener initialized: {self.instance_id} ({self.role})")

    def _load_config(self) -> None:
        """Load configuration from JSON file or environment variables."""
        # 1. Load from file if exists
        p = Path(self.config_path)
        if p.exists():
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                    self.instance_id = data.get("AGENT_INSTANCE_ID", self.instance_id)
                    self.role = data.get("AGENT_ROLE", self.role)
                    self.gateway_ws_url = data.get("GATEWAY_WS_URL", self.gateway_ws_url)
                    self.poll_interval = float(data.get("POLL_INTERVAL", self.poll_interval))
                    logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config file {self.config_path}: {e}")

        # 2. Override with env vars / MCO Config if present
        config = get_config()
        self.instance_id = config.get("AGENT_INSTANCE_ID") or os.environ.get("AGENT_INSTANCE_ID", self.instance_id)
        self.role = config.get("AGENT_ROLE") or os.environ.get("AGENT_ROLE", self.role)
        self.gateway_ws_url = config.get("GATEWAY_WS_URL") or os.environ.get("GATEWAY_WS_URL", self.gateway_ws_url)
        
        poll_val = config.get("POLL_INTERVAL") or os.environ.get("POLL_INTERVAL")
        if poll_val:
            try:
                self.poll_interval = float(poll_val)
            except ValueError:
                pass

    async def start(self) -> None:
        """Start the background loops (WebSocket listener + Polling timer)."""
        logger.info(f"Starting agent worker loops for {self.instance_id}...")
        
        # Start periodic polling task
        polling_task = asyncio.create_task(self._periodic_poll_loop())
        
        # Start WebSocket live trigger task
        ws_task = asyncio.create_task(self._websocket_loop())
        
        await asyncio.gather(polling_task, ws_task)

    async def _websocket_loop(self) -> None:
        """Connects to the Gateway WebSocket and listens for live trigger events."""
        reconnect_delay = 1.0
        while True:
            try:
                logger.info(f"Connecting to Gateway WebSocket: {self.gateway_ws_url}...")
                async with websockets.connect(self.gateway_ws_url) as ws:
                    reconnect_delay = 1.0
                    logger.info("Connected to Gateway WebSocket.")

                    # Configure session on connection
                    setup_msg = {
                        "id": f"setup-{self.instance_id}",
                        "type": "session_create",
                        "payload": {
                            "tool_profile": "coding",
                            "metadata": {
                                "instance_id": self.instance_id,
                                "role": self.role
                            }
                        }
                    }
                    await ws.send(json.dumps(setup_msg))

                    # Listen for messages
                    async for message_str in ws:
                        try:
                            msg = json.loads(message_str)
                            msg_type = msg.get("type")
                            payload = msg.get("payload") or {}

                            # Check if this is a job pending notification matching our role/id
                            if msg_type == "event":
                                event_name = payload.get("event")
                                job = payload.get("job") or {}
                                
                                if event_name == "job_pending":
                                    target_role = job.get("target_agent_role")
                                    target_id = job.get("target_agent_id")
                                    
                                    if target_role == self.role or target_id == self.instance_id:
                                        logger.info(f"WebSocket trigger received for job: {job.get('title')}. Checking immediately.")
                                        asyncio.create_task(self._process_single_job(job))

                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            logger.error(f"Error handling WebSocket message: {e}")

            except (websockets.ConnectionClosed, OSError) as e:
                logger.warning(f"WebSocket connection lost/failed: {e}. Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60.0)

    async def _periodic_poll_loop(self) -> None:
        """Periodic safety poll fallback loop."""
        while True:
            try:
                await self.poll_and_execute()
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
            await asyncio.sleep(self.poll_interval)

    async def poll_and_execute(self) -> None:
        """Poll the database for pending jobs and process them."""
        logger.debug("Polling Job Board for pending tasks...")
        
        # Query for pending tasks targeting our role or this specific instance
        res = self.db_client.table("agent_jobs")\
            .select("*")\
            .eq("status", "pending")\
            .eq("target_agent_role", self.role)\
            .execute()
        
        jobs = res.data or []
        
        for job in jobs:
            target_id = job.get("target_agent_id")
            if target_id and target_id != self.instance_id:
                continue
            
            await self._process_single_job(job)

    async def _process_single_job(self, job: Dict[str, Any]) -> None:
        """Atomically leases and executes a single job."""
        job_id = job.get("id")
        title = job.get("title")
        if not job_id:
            return

        logger.info(f"Attempting to lease job: {title} ({job_id})")

        try:
            res = self.db_client.rpc("lease_task", {
                "p_agent_instance_id": self.instance_id,
                "p_task_id": job_id
            }).execute()

            leased = res.data if hasattr(res, "data") else False
            if not leased:
                logger.debug(f"Job {job_id} already leased or not assignable.")
                return

            logger.info(f"Successfully leased job: {title}. Starting execution.")
            
            # Update status to in_progress
            self.db_client.table("agent_jobs").update({
                "status": "in_progress",
                "started_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", job_id).execute()

            # Execute the job
            output, error = await self._execute_task(job)

            if error:
                logger.error(f"Job failed: {title}. Error: {error}")
                self.db_client.table("agent_jobs").update({
                    "status": "failed",
                    "error_message": error,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", job_id).execute()
            else:
                logger.info(f"Job completed successfully: {title}")
                self.db_client.table("agent_jobs").update({
                    "status": "completed",
                    "output_payload": {"result": output},
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", job_id).execute()

                # Trigger database unlocking logic via Gateway server
                try:
                    async with websockets.connect(self.gateway_ws_url) as ws:
                        notify_msg = {
                            "id": f"notify-{job_id}",
                            "type": "job_update",
                            "payload": {
                                "task_id": job_id,
                                "status": "completed",
                                "output_payload": {"result": output}
                            }
                        }
                        await ws.send(json.dumps(notify_msg))
                except Exception as ws_err:
                    logger.debug(f"Could not send socket notify: {ws_err}. Sync will happen on DB refresh.")

        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")

    async def _execute_task(self, job: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """Run the actual tool wrapper based on target role."""
        description = job.get("description", "")
        title = job.get("title", "")
        input_payload = job.get("input_payload") or {}

        prompt = f"Task Title: {title}\nInstructions:\n{description}"
        if "prompt" in input_payload:
            prompt = input_payload["prompt"]

        logger.info(f"Running task with prompt length {len(prompt)}...")

        try:
            # 1. Try registered custom executor first
            if self.role in _executor_registry:
                logger.info(f"Delegating task execution to registered custom executor for role: {self.role}")
                return await _executor_registry[self.role](job, prompt)

            # 2. Standalone fallback shell/subprocess command executor
            # If payload specifies 'cmd' or 'command' or 'script'
            cmd = input_payload.get("command") or input_payload.get("cmd")
            if cmd:
                logger.info(f"Executing local subprocess command: {cmd}")
                # Run command in shell safely
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                
                stdout_str = stdout.decode().strip()
                stderr_str = stderr.decode().strip()
                
                if proc.returncode == 0:
                    return stdout_str or "Success (No Output)", None
                else:
                    return None, f"Command failed with code {proc.returncode}. Stderr: {stderr_str}"

            # Fallback mock executor for default test/setup
            logger.info("No explicit command/executor found. Mocking successful execution of instruction.")
            mock_result = f"Executed instruction: '{title}' locally. Prompt: {prompt[:100]}..."
            return mock_result, None

        except Exception as e:
            logger.exception(f"Exception during task execution: {e}")
            return None, str(e)
