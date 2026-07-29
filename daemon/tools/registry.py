"""
Tool Registry & Schema Validator Module (Sub-Task 2.1)
Manages JSON-based custom tool manifests and validates tool definitions.
"""

import os
import json
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
                "description": "Launches a desktop application on Linux. Cause: User says 'open Steam' or 'launch Firefox'. Effect: Starts and displays the target application window.",
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
                    "template": "gtk-launch '{app_name}' || gio launch '/usr/share/applications/{app_name}.desktop' || {app_name} &"
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

        return len(self._tools)

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
        Formats all registered custom tools into a clean prompt string for the LLM,
        including explicit Cause (User Request) and Effect (Tool Action) examples.
        """
        if not self._tools:
            return "No custom user tools registered."

        descriptions = []
        for tool in self._tools.values():
            clean_desc = tool.description.split(" Cause:")[0].strip()
            desc = f"- **{tool.id}** ({tool.name}): {clean_desc}\n"
            desc += f"  Parameters JSON Schema: {json.dumps(tool.parameters.get('properties', {}))}\n"
            if tool.examples:
                ex = tool.examples[0]
                prompt_clean = ex.user_prompt.replace("Cause: ", "").replace("Effect: ", "").strip()
                desc += f"  Example (Cause & Effect):\n"
                desc += f"    • Cause (User Request): \"{prompt_clean}\"\n"
                desc += f"    • Effect (Tool Action): Execute '{tool.id}' with args {json.dumps(ex.expected_args)}\n"
            descriptions.append(desc)

        return "\n".join(descriptions)
