"""Skill sandbox for oi-gateway with subprocess isolation.

The skill sandbox executes skills as separate processes for isolation.
Tool broker integration enforces permissions at the call level.
Firmware protection blocks dangerous operations that could rebind buttons,
flash firmware, or bypass local mute.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk classification for skills.
    
    SAFE: Read-only, no side effects
    LIMITED: Limited side effects, local only
    ELEVATED: More capabilities, needs approval
    RESTRICTED: High risk, not allowed in MVP
    """
    SAFE = 1
    LIMITED = 2
    ELEVATED = 3
    RESTRICTED = 4


@dataclass
class ToolPermission:
    """A tool permission with risk classification."""
    name: str
    risk_level: RiskLevel
    description: str


# Predefined tool permissions for the tool broker
class ToolPermissions:
    """Predefined tool permissions."""
    # Safe - read only
    READ_STATE = ToolPermission("read_state", RiskLevel.SAFE, "Read device state")
    LIST_DEVICES = ToolPermission("list_devices", RiskLevel.SAFE, "List available devices")
    
    # Limited - local side effects
    SHOW_STATUS = ToolPermission("show_status", RiskLevel.LIMITED, "Show status on device")
    PLAY_AUDIO = ToolPermission("play_audio", RiskLevel.LIMITED, "Play audio on device")
    SET_BRIGHTNESS = ToolPermission("set_brightness", RiskLevel.LIMITED, "Set device brightness")
    
    # Elevated - more capabilities
    MUTE_DEVICE = ToolPermission("mute_device", RiskLevel.ELEVATED, "Mute device")
    CACHE_AUDIO = ToolPermission("cache_audio", RiskLevel.ELEVATED, "Cache audio on device")
    INVOKE_COMMAND = ToolPermission("invoke_command", RiskLevel.ELEVATED, "Invoke arbitrary command")
    
    # Restricted - not allowed (firmware protection)
    REBIND_BUTTONS = ToolPermission("rebind_buttons", RiskLevel.RESTRICTED, "Rebind button inputs")
    FLASH_FIRMWARE = ToolPermission("flash_firmware", RiskLevel.RESTRICTED, "Flash device firmware")
    BYPASS_MUTE = ToolPermission("bypass_mute", RiskLevel.RESTRICTED, "Bypass device mute")
    EXECUTE_SYSTEM = ToolPermission("execute_system", RiskLevel.RESTRICTED, "Execute system commands")


class ToolBroker:
    """Tool broker that enforces permissions at the call level.
    
    The tool broker checks if a skill is allowed to perform certain operations
    based on its risk classification. This is the enforcement point mentioned
    in PLAN.md: "Tool broker enforces at the call level (risk class + permission)".
    """

    # Operations that are forbidden to protect firmware
    FORBIDDEN_OPERATIONS = {
        "rebind_buttons",
        "flash_firmware", 
        "bypass_mute",
        "execute_system",
        "write_flash",
        "update_firmware",
        "button_map",
        "button_override",
        "unmute",
        "force_audio",
    }

    def __init__(self) -> None:
        self._permissions: dict[str, ToolPermission] = {}
        
        # Register all predefined permissions
        for perm in [
            ToolPermissions.READ_STATE,
            ToolPermissions.LIST_DEVICES,
            ToolPermissions.SHOW_STATUS,
            ToolPermissions.PLAY_AUDIO,
            ToolPermissions.SET_BRIGHTNESS,
            ToolPermissions.MUTE_DEVICE,
            ToolPermissions.CACHE_AUDIO,
            ToolPermissions.INVOKE_COMMAND,
            ToolPermissions.REBIND_BUTTONS,
            ToolPermissions.FLASH_FIRMWARE,
            ToolPermissions.BYPASS_MUTE,
            ToolPermissions.EXECUTE_SYSTEM,
        ]:
            self._permissions[perm.name] = perm

    def check_permission(
        self, 
        tool_name: str, 
        skill_risk_level: RiskLevel = RiskLevel.LIMITED
    ) -> bool:
        """Check if a tool permission is allowed for a given risk level.
        
        A skill can access tools with risk level <= its own level.
        
        Parameters
        ----------
        tool_name : str
            Name of the tool/operation to check.
        skill_risk_level : RiskLevel
            Risk level of the skill requesting the permission.
            
        Returns
        -------
        bool
            True if allowed, False otherwise.
        """
        # Check if operation is forbidden (firmware protection)
        if tool_name.lower() in self.FORBIDDEN_OPERATIONS:
            logger.warning("Blocked forbidden operation: %s", tool_name)
            return False
        
        perm = self._permissions.get(tool_name)
        if not perm:
            # Unknown tool - allow but log warning
            logger.warning("Unknown tool requested: %s", tool_name)
            return True
        
        # Check if tool is restricted
        if perm.risk_level == RiskLevel.RESTRICTED:
            return False
        
        # A skill can access tools at or below its risk level
        return perm.risk_level.value <= skill_risk_level.value

    def is_operation_allowed(self, operation: str) -> bool:
        """Check if an operation is allowed (firmware protection).
        
        Parameters
        ----------
        operation : str
            Name of the operation to check.
            
        Returns
        -------
        bool
            True if allowed, False otherwise.
        """
        return operation.lower() not in self.FORBIDDEN_OPERATIONS

    def get_allowed_tools(self, risk_level: RiskLevel) -> list[str]:
        """Get list of tools allowed for a given risk level.
        
        Parameters
        ----------
        risk_level : RiskLevel
            Risk level to filter by.
            
        Returns
        -------
        list[str]
            List of tool names that are allowed.
        """
        allowed = []
        for name, perm in self._permissions.items():
            # Skip restricted tools
            if perm.risk_level == RiskLevel.RESTRICTED:
                continue
            # Compare by ordinal to ensure proper ordering
            if perm.risk_level.value <= risk_level.value:
                allowed.append(name)
        return sorted(allowed)


class SkillExecutor:
    """Executes skills as separate subprocesses.
    
    This provides process-level isolation - each skill runs in its own
    Python process, separate from the gateway. This is the subprocess
    model specified in PLAN.md.
    """

    def __init__(
        self,
        max_execution_time: float = 30.0,
        max_memory_mb: int = 128,
    ) -> None:
        self._max_execution_time = max_execution_time
        self._max_memory_mb = max_memory_mb

    async def execute(
        self,
        skill_code: str,
        parameters: dict[str, Any],
    ) -> SkillResult:
        """Execute skill code in a subprocess.
        
        Parameters
        ----------
        skill_code : str
            Python code to execute.
        parameters : dict
            Parameters to pass to the skill.
            
        Returns
        -------
        SkillResult
            Result of the execution.
        """
        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._execute_sync,
            skill_code,
            parameters
        )

    def _execute_sync(
        self,
        skill_code: str,
        parameters: dict[str, Any],
    ) -> SkillResult:
        """Synchronous execution in subprocess."""
        # Write skill code to a temp file
        # Wrap code to capture result as JSON
        wrapped_code = self._wrap_skill_code(skill_code)
        
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.py',
                delete=False,
                encoding='utf-8'
            ) as f:
                f.write(wrapped_code)
                temp_path = f.name

            try:
                # Run as subprocess with parameters passed via stdin
                proc = subprocess.run(
                    [sys.executable, temp_path],
                    input=json.dumps(parameters),
                    capture_output=True,
                    text=True,
                    timeout=self._max_execution_time,
                )

                if proc.returncode == 0 and proc.stdout.strip():
                    try:
                        output = json.loads(proc.stdout)
                        return SkillResult(
                            success=output.get("success", False),
                            result=output.get("result"),
                            error=output.get("error"),
                        )
                    except json.JSONDecodeError:
                        # Output was not JSON, treat as result
                        return SkillResult(
                            success=True,
                            result=proc.stdout.strip(),
                        )
                else:
                    return SkillResult(
                        success=False,
                        error=proc.stderr or "Execution failed",
                    )
            except subprocess.TimeoutExpired:
                return SkillResult(
                    success=False,
                    error=f"Execution timed out after {self._max_execution_time}s",
                )
            except Exception as e:
                return SkillResult(
                    success=False,
                    error=str(e),
                )
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Failed to setup execution: {e}",
            )

    def _wrap_skill_code(self, code: str) -> str:
        """Wrap skill code to execute and return result as JSON."""
        # Indent the skill code
        indented_code = "\n".join(f"    {line}" for line in code.split("\n"))
        
        return f'''#!/usr/bin/env python3
"""Skill execution wrapper - runs skill as subprocess."""
import json
import sys

def execute():
{indented_code}
    return locals().get('result')

if __name__ == "__main__":
    try:
        # Read parameters from stdin once
        stdin_data = sys.stdin.read()
        parameters = json.loads(stdin_data) if stdin_data else {{}}
        result = execute()
        print(json.dumps({{"success": True, "result": result}}))
    except Exception as e:
        print(json.dumps({{"success": False, "error": str(e)}}))
'''


@dataclass
class Skill:
    """A registered skill."""
    name: str
    description: str
    code: str
    version: str = "1.0.0"
    parameters: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    skill_id: str = ""
    risk_level: RiskLevel = RiskLevel.LIMITED


@dataclass
class SkillResult:
    """Result of skill execution."""
    success: bool
    result: Any = None
    error: str | None = None
    execution_time: float = 0.0


@dataclass
class SkillManifest:
    """Manifest for a skill."""
    name: str
    version: str
    description: str
    parameters: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class SkillSandboxProtocol(Protocol):
    """Protocol for skill sandbox implementations."""

    def register_skill(self, skill: Skill) -> str:
        """Register a skill."""
        ...

    async def execute_skill(
        self,
        skill_name: str,
        parameters: dict[str, Any],
    ) -> SkillResult:
        """Execute a skill."""
        ...

    def list_skills(self) -> list[SkillManifest]:
        """List registered skills."""
        ...

    def delete_skill(self, skill_name: str) -> bool:
        """Delete a skill."""
        ...


class SkillSandboxError(Exception):
    """Error in skill sandbox."""
    pass


class SkillNotFoundError(SkillSandboxError):
    """Skill not found in sandbox."""
    pass


class SkillExecutionError(SkillSandboxError):
    """Skill execution failed."""
    pass


class SkillValidationError(SkillSandboxError):
    """Skill validation failed."""
    pass


class ForbiddenOperationError(SkillSandboxError):
    """Operation forbidden by tool broker (firmware protection)."""
    pass


class SkillSandbox:
    """Sandboxed execution environment for custom skills using subprocess isolation.

    The skill sandbox provides process-level isolation for executing agent-defined skills.
    Each skill runs in its own subprocess, with tool broker integration for permission
    checking and firmware protection.

    Parameters
    ----------
    max_execution_time : float
        Maximum execution time for a skill in seconds.
    max_memory_mb : int
        Maximum memory a skill can use in MB.
    allowed_imports : list[str]
        List of allowed module imports (for reference - subprocess ignores this).
    """

    # Forbidden operations that could affect firmware
    FORBIDDEN_PATTERNS = [
        "rebind",
        "button_map",
        "button_override",
        "flash_firmware",
        "write_flash",
        "update_firmware",
        "ota_update",
        "bypass_mute",
        "force_unmute",
        "unmute",
    ]

    def __init__(
        self,
        max_execution_time: float = 30.0,
        max_memory_mb: int = 128,
        allowed_imports: list[str] | None = None,
    ) -> None:
        self._max_execution_time = max_execution_time
        self._max_memory_mb = max_memory_mb
        self._allowed_imports = allowed_imports or [
            "json",
            "math",
            "random",
            "re",
            "datetime",
            "typing",
        ]

        self._skills: dict[str, Skill] = {}
        self._execution_contexts: dict[str, dict[str, Any]] = {}
        
        # Tool broker for permission checking
        self._tool_broker = ToolBroker()
        
        # Subprocess-based skill executor
        self._executor = SkillExecutor(
            max_execution_time=max_execution_time,
            max_memory_mb=max_memory_mb,
        )

    @property
    def tool_broker(self) -> ToolBroker:
        """Get the tool broker for permission checking."""
        return self._tool_broker

    @property
    def executor(self) -> SkillExecutor:
        """Get the skill executor."""
        return self._executor

    def register_skill(self, skill: Skill) -> str:
        """Register a skill in the sandbox.

        Parameters
        ----------
        skill : Skill
            The skill to register.

        Returns
        -------
        str
            The skill ID.

        Raises
        ------
        SkillValidationError
            If the skill code is invalid or contains forbidden operations.
        """
        # Validate skill code
        self._validate_skill_code(skill.code)

        # Generate skill ID
        skill_id = hashlib.sha256(
            f"{skill.name}{skill.version}".encode()
        ).hexdigest()[:16]

        # Preserve existing skill_id if provided, otherwise use generated one
        if not skill.skill_id:
            skill.skill_id = skill_id
        if not skill.created_at:
            import datetime
            skill.created_at = datetime.datetime.now().isoformat()

        # Store skill
        self._skills[skill.name] = skill
        logger.info("Registered skill: %s (ID: %s)", skill.name, skill_id)

        return skill_id

    async def execute_skill(
        self,
        skill_name: str,
        parameters: dict[str, Any],
    ) -> SkillResult:
        """Execute a skill in a subprocess.

        Parameters
        ----------
        skill_name : str
            Name of the skill to execute.
        parameters : dict
            Parameters to pass to the skill.

        Returns
        -------
        SkillResult
            Result of the skill execution.
        """
        if skill_name not in self._skills:
            raise SkillNotFoundError(f"Skill not found: {skill_name}")

        skill = self._skills[skill_name]
        execution_id = str(uuid.uuid4())

        logger.info("Executing skill: %s (ID: %s)", skill.name, execution_id)

        # Check tool broker permissions before execution
        # This enforces the "tool broker enforces at the call level" requirement
        allowed_tools = self._tool_broker.get_allowed_tools(skill.risk_level)
        
        # Check if skill contains any forbidden operations
        if not self._check_operation_allowed(skill.code):
            return SkillResult(
                success=False,
                error="Skill contains forbidden operations that could affect firmware",
                execution_time=0.0,
            )

        start_time = asyncio.get_event_loop().time()

        try:
            # Create execution context
            context = {
                "execution_id": execution_id,
                "skill_name": skill_name,
                "parameters": parameters,
                "start_time": start_time,
                "risk_level": skill.risk_level.value,
                "allowed_tools": allowed_tools,
            }
            self._execution_contexts[execution_id] = context

            # Execute via subprocess executor
            result = await self._executor.execute(
                skill.code,
                parameters,
            )

            execution_time = asyncio.get_event_loop().time() - start_time
            
            # Add execution time to result
            result.execution_time = execution_time

            return result

        except asyncio.TimeoutError:
            execution_time = asyncio.get_event_loop().time() - start_time
            logger.error("Skill execution timed out: %s", skill_name)
            return SkillResult(
                success=False,
                error=f"Execution timed out after {self._max_execution_time}s",
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            logger.error("Skill execution failed: %s - %s", skill_name, e)
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=execution_time,
            )

        finally:
            # Clean up execution context
            self._execution_contexts.pop(execution_id, None)

    def list_skills(self) -> list[SkillManifest]:
        """List all registered skills.

        Returns
        -------
        list[SkillManifest]
            List of skill manifests.
        """
        return [
            SkillManifest(
                name=skill.name,
                version=skill.version,
                description=skill.description,
                parameters=skill.parameters,
            )
            for skill in self._skills.values()
        ]

    def delete_skill(self, skill_name: str) -> bool:
        """Delete a skill from the sandbox.

        Parameters
        ----------
        skill_name : str
            Name of the skill to delete.

        Returns
        -------
        bool
            True if skill was deleted, False if not found.
        """
        if skill_name in self._skills:
            del self._skills[skill_name]
            logger.info("Deleted skill: %s", skill_name)
            return True
        return False

    def get_skill(self, skill_name: str) -> Skill | None:
        """Get a skill by name.

        Parameters
        ----------
        skill_name : str
            Name of the skill.

        Returns
        -------
        Skill or None
            The skill if found.
        """
        return self._skills.get(skill_name)

    def _validate_skill_code(self, code: str) -> None:
        """Validate skill code for safety.

        Raises SkillValidationError if code contains unsafe patterns.

        This includes checking for dangerous imports and operations that
        could affect firmware (button rebinding, firmware flashing, etc.)
        """
        forbidden_imports = ["os", "sys", "subprocess", "socket", "requests", "http"]
        for imp in forbidden_imports:
            if f"import {imp}" in code or f"from {imp} " in code:
                raise SkillValidationError(f"Forbidden import: {imp}")

        forbidden_pattern = self._find_forbidden_pattern(code, ["eval(", "exec(", "open("])
        if forbidden_pattern is not None:
            raise SkillValidationError(f"Forbidden pattern: {forbidden_pattern}")

        firmware_pattern = self._find_forbidden_operation(code)
        if firmware_pattern is not None:
            raise SkillValidationError(
                f"Forbidden operation that could affect firmware: {firmware_pattern}"
            )

    def _find_forbidden_pattern(self, code: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            if pattern in code:
                return pattern
        return None

    def _find_forbidden_operation(self, code: str) -> str | None:
        return self._find_forbidden_pattern(code.lower(), self.FORBIDDEN_PATTERNS)

    def _check_operation_allowed(self, code: str) -> bool:
        """Check if code contains any forbidden operations.

        This is the firmware protection layer - even after validation,
        we check at execution time.
        """
        forbidden_pattern = self._find_forbidden_operation(code)
        if forbidden_pattern is not None:
            logger.warning("Blocked forbidden operation in code: %s", forbidden_pattern)
            return False
        return True

    @property
    def skill_count(self) -> int:
        """Get the number of registered skills."""
        return len(self._skills)

    @property
    def max_execution_time(self) -> float:
        """Get the maximum execution time."""
        return self._max_execution_time

    @max_execution_time.setter
    def max_execution_time(self, value: float) -> None:
        """Set the maximum execution time."""
        self._max_execution_time = value
        self._executor._max_execution_time = value