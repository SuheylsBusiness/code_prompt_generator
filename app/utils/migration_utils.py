# File: app/utils/migration_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import os
import json
import logging
import time
import hashlib
from app.config import CACHE_DIR, PROJECTS_DIR

logger = logging.getLogger(__name__)

def get_safe_project_foldername(project_name: str) -> str:
    """Generates a safe, unique folder name for a project."""
    sanitized_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '_', '-')).rstrip()
    # Use a short hash of the original name to ensure uniqueness
    short_hash = hashlib.md5(project_name.encode('utf-8')).hexdigest()[:8]
    return f"{sanitized_name}-{short_hash}"

def perform_migration_if_needed():
    """
    Checks for the legacy projects.json file and migrates its contents
    to the new per-project folder structure. This runs only once.
    """
    legacy_projects_file = os.path.join(CACHE_DIR, 'projects.json')
    if not os.path.exists(legacy_projects_file):
        return # No migration needed

    logger.warning("Legacy 'projects.json' file found. Starting one-time migration.")

    try:
        with open(legacy_projects_file, 'r', encoding='utf-8') as f:
            old_projects_data = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Could not read or parse legacy projects.json. Migration failed. Error: {e}")
        # Rename the corrupt legacy file to prevent retries and app failure
        os.rename(legacy_projects_file, f"{legacy_projects_file}.corrupt.{int(time.time())}")
        return

    os.makedirs(PROJECTS_DIR, exist_ok=True)
    migration_successful = True

    for project_name, project_data in old_projects_data.items():
        try:
            logger.info(f"Migrating project: {project_name}")
            folder_name = get_safe_project_foldername(project_name)
            project_folder_path = os.path.join(PROJECTS_DIR, folder_name)
            os.makedirs(project_folder_path, exist_ok=True)
            
            # The new project file doesn't need a lock during migration
            # as the app isn't fully running yet.
            project_file_path = os.path.join(project_folder_path, 'project.json')
            project_lock_path = os.path.join(project_folder_path, 'project.json.lock')

            # The project name is now part of the data, not the top-level key
            project_data['name'] = project_name

            # Use a direct write, as atomic_write isn't set up for this yet
            with open(project_file_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=4)

        except Exception as e:
            logger.error(f"Failed to migrate project '{project_name}'. Error: {e}", exc_info=True)
            migration_successful = False
            break # Stop migration on first error

    if migration_successful:
        migrated_filename = f"{legacy_projects_file}.migrated.{int(time.time())}"
        os.rename(legacy_projects_file, migrated_filename)
        logger.warning(f"Migration successful. Legacy file renamed to {os.path.basename(migrated_filename)}")
    else:
        logger.error("Migration failed. Please check the logs. The legacy projects.json was NOT renamed.")