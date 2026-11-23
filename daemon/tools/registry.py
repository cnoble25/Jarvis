"""
Tool Registry & Schema Validator Module (Sub-Task 2.1)
Manages JSON-based custom tool manifests and validates tool definitions.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ValidationError


class ExecutionConfig(BaseModel):
    type: str = "command_template"  # 'command_template' or 'script'
    template: str  # Shell command template (e.g. "gio launch '{app_name}'")


class ToolExample(BaseModel):
    user_prompt: str
    expected_args: Dict[str, Any] = Field(default_factory=dict)


class ToolManifest(BaseModel):
    id: str
    name: str
    version: str = "1.0.0"
    description: str
    category: str = "general"
    parameters: Dict[str, Any] = Field(default_factory=dict)  # JSON Schema for arguments
    execution: ExecutionConfig
    examples: List[ToolExample] = Field(default_factory=list)
    risk_level: str = "MEDIUM"  # 'SAFE', 'MEDIUM', 'HIGH'
    spoken_confirmation_template: Optional[str] = None


class ToolRegistry:
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize ToolRegistry and load JSON manifests from config directory.
        
        :param config_dir: Directory containing custom tool JSON manifests.
        """
        if config_dir is None:
            config_dir = os.path.expanduser("~/.config/jarvis/tools")
        
        self.config_dir = config_dir
        os.makedirs(self.config_dir, exist_ok=True)
        # Skills Jarvis wrote for itself live next to the tools folder (~/.config/jarvis/skills).
        from .skills import SkillStore
        self.skills = SkillStore(Path(self.config_dir).parent / "skills")

        self._tools: Dict[str, ToolManifest] = {}
        self._create_default_manifests()
        self.reload_tools()

    def _create_default_manifests(self):
        """
        Populates default custom JSON tool manifests if directory is empty.
        """
        defaults = [
            {
                "id": "app_launcher",
                "name": "Launch Desktop Application",
                "version": "1.0.0",
                "description": "Launches an installed desktop application. Cause: User says 'open Steam' or 'launch Firefox'. Effect: Starts and displays the target application window.",
                "category": "system",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Name or executable binary of the application (e.g. 'code', 'firefox', 'alacritty')."
                        }
                    },
                    "required": ["app_name"]
                },
                "execution": {
                    "type": "command_template",
                    "template": "builtin_app_launcher"  # handled in ExecutionEngine through the OS interface
                },
                "examples": [
                    {
                        "user_prompt": "Open VS Code",
                        "expected_args": {"app_name": "code"}
                    }
                ],
                "risk_level": "MEDIUM",
                "spoken_confirmation_template": "Opened {app_name}."
            }
        ]

        for manifest_data in defaults:
            file_path = os.path.join(self.config_dir, f"{manifest_data['id']}.json")
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(manifest_data, f, indent=2)

        # Copy/sync daily_commands.json to config_dir if available
        daily_json_src = os.path.join(os.path.dirname(__file__), "daily_commands.json")
        daily_json_dst = os.path.join(self.config_dir, "daily_commands.json")
        if os.path.exists(daily_json_src):
            try:
                import shutil
                shutil.copy(daily_json_src, daily_json_dst)
                print(f"[ToolRegistry] Synced daily life commands manifest to {daily_json_dst}", flush=True)
            except Exception as e:
                print(f"[ToolRegistry Warning] Could not copy daily_commands.json: {e}", flush=True)


    def reload_tools(self) -> int:
        """
        Scans config_dir and loads/validates all JSON tool manifests.
        
        :return: Count of loaded tools.
        """
        self._tools.clear()
        if not os.path.exists(self.config_dir):
            return 0

        for filename in sorted(os.listdir(self.config_dir)):
            if filename.endswith(".json"):
                file_path = os.path.join(self.config_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    if isinstance(data, list):
                        for item in data:
                            manifest = ToolManifest.model_validate(item)
                            self._tools[manifest.id] = manifest
                            print(f"[ToolRegistry] Loaded tool: '{manifest.id}' ({manifest.name})", flush=True)
                    else:
                        manifest = ToolManifest.model_validate(data)
                        self._tools[manifest.id] = manifest
                        print(f"[ToolRegistry] Loaded tool: '{manifest.id}' ({manifest.name})", flush=True)
                except (json.JSONDecodeError, ValidationError) as e:
                    print(f"[ToolRegistry Error] Failed to parse manifest '{filename}': {e}", flush=True)

        # Approved skills, unless a command with the same id exists (a skill never shadows one).
        for data in self.skills.approved_manifests():
            try:
                manifest = ToolManifest.model_validate(data)
            except ValidationError as e:
                print(f"[ToolRegistry Error] Skill '{data.get('id')}' has an invalid manifest: {e}", flush=True)
                continue
            if manifest.id not in self._tools:
                self._tools[manifest.id] = manifest
                print(f"[ToolRegistry] Loaded skill: '{manifest.id}' ({manifest.name})", flush=True)

        return len(self._tools)

    def is_skill(self, tool_id: str) -> bool:
        tool = self._tools.get(tool_id)
        return bool(tool and tool.execution.type == "skill")

    def register_tool(self, manifest_data: Dict[str, Any]) -> ToolManifest:
        """
        Registers a new custom tool manifest and saves it to a JSON file.
        """
        manifest = ToolManifest.model_validate(manifest_data)
        file_path = os.path.join(self.config_dir, f"{manifest.id}.json")
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(), f, indent=2)

        self._tools[manifest.id] = manifest
        print(f"[ToolRegistry] Registered custom tool '{manifest.id}' -> {file_path}", flush=True)
        return manifest

    def unregister_tool(self, tool_id: str) -> bool:
        """
        Removes a custom tool by ID and deletes its JSON manifest file.
        """
        if self.is_skill(tool_id):
            del self._tools[tool_id]
            return self.skills.delete(tool_id)
        if tool_id in self._tools:
            del self._tools[tool_id]
            file_path = os.path.join(self.config_dir, f"{tool_id}.json")
            if os.path.exists(file_path):
                os.remove(file_path)
            print(f"[ToolRegistry] Unregistered tool '{tool_id}'", flush=True)
            return True
        return False

    def get_tool(self, tool_id: str) -> Optional[ToolManifest]:
        """
        Retrieves a loaded ToolManifest by ID.
        """
        return self._tools.get(tool_id)

    def list_tools(self) -> List[ToolManifest]:
        """
        Returns a list of all registered tool manifests.
        """
        return list(self._tools.values())

    def get_llm_tool_descriptions(self) -> str:
        """
        The tools for the LLM system prompt, compactly: this is sent with every request, so every
        line costs on every turn. One line each for what it does, its arguments (type shown when
        it isn't plain text), and an example: "what the user says" -> {args}.
        """
        if not self._tools:
            return "No custom user tools registered."

        descriptions = []
        for tool in self._tools.values():
            lines = [f"- {tool.id}: {tool.description.split(' Cause:')[0].strip()}"]
            args = []
            for name, spec in (tool.parameters.get("properties") or {}).items():
                spec = spec if isinstance(spec, dict) else {}
                kind = spec.get("type", "string")
                if kind == "array":
                    kind = f"list of {(spec.get('items') or {}).get('type', 'items')}"
                label = name if kind == "string" else f"{name} ({kind})"
                if spec.get("enum"):
                    label += " = " + "|".join(str(v) for v in spec["enum"])
                desc = str(spec.get("description", "")).strip()
                args.append(f"{label}: {desc}" if desc else label)
            lines.append("  args: " + ("; ".join(args) if args else "none"))
            if tool.examples:
                ex = tool.examples[0]
                said = ex.user_prompt.replace("Cause: ", "").replace("Effect: ", "").strip()
                lines.append(f'  e.g. "{said}" -> {json.dumps(ex.expected_args)}')
            descriptions.append("\n".join(lines))

        return "\n".join(descriptions)
