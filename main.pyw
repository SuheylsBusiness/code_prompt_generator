# File: code_prompt_generator/main.pyw
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

import logging, traceback, sys, os
from app.models.project_model import ProjectModel
from app.models.settings_model import SettingsModel
from app.views.main_view import MainView
from app.controllers.main_controller import MainController
from app.config import load_config, initialize_logging
from app.utils.ui_helpers import show_error_centered

# Main Execution
# ------------------------------
if __name__ == "__main__":
	controller = None
	try:
		load_config()
		initialize_logging()
		settings_model = SettingsModel()
		project_model = ProjectModel(settings_model)
		if not settings_model.is_loaded() or not project_model.is_loaded():
			show_error_centered(None, "Fatal Error", "Could not load data files due to a file lock. Please close other instances.")
			sys.exit(1)
		controller = MainController(project_model, settings_model)
		app = MainView(controller)
		controller.set_view(app)
		app.mainloop()
	except Exception as e:
		logging.getLogger(__name__).error("Fatal Error: %s\n%s", e, traceback.format_exc())
		print(f"A fatal error occurred: {e}", file=sys.stderr)
		show_error_centered(None, "Fatal Error", f"A fatal error occurred:\n{e}")
	finally:
		if controller:
			logging.info("Performing final resource cleanup.")
			controller.project_model.stop_threads()
			controller.stop_threads()