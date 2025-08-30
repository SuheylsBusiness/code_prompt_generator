# File: app/custom_scripts/manager.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

from app.config import get_logger
from app.custom_scripts.header_formatter import HeaderFormatterScript

logger = get_logger(__name__)

# Manager
# ------------------------------
class CustomScriptsManager:
	def __init__(self, controller):
		self.controller = controller
		self.registry = {"header_formatter": HeaderFormatterScript(controller)}

	def run_script(self, script_id, root_dir, visible_relative_paths):
		if script_id not in self.registry: raise RuntimeError(f"Unknown custom script: {script_id}")
		return self.registry[script_id].run(root_dir, visible_relative_paths)