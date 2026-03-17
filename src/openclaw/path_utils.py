import os
from pathlib import Path

def get_repo_root() -> Path:
    """
    Returns the absolute path to the repository root.
    It first checks for the OPENCLAW_ROOT_ENV environment variable.
    If not set, it infers the root from this file's location.
    """
    env_root = os.getenv("OPENCLAW_ROOT_ENV")
    if env_root:
        return Path(env_root).resolve()
    
    # This file is located at src/openclaw/path_utils.py
    # So the repo root is 2 parents up.
    return Path(__file__).resolve().parent.parent.parent

def get_config_path(filename: str) -> Path:
    """
    Returns the absolute path to a configuration file located in the config directory.
    """
    return get_repo_root() / "config" / filename

def get_data_path(filename: str = "") -> Path:
    """
    Returns the absolute path to the data directory or a specific file within it.
    """
    data_dir = get_repo_root() / "data"
    if filename:
        return data_dir / filename
    return data_dir
