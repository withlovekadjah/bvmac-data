import os
from pathlib import Path

# Keep the cache out of the user's project so they can start from any folder.
DATA_HOME = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "bvmac-data"
DEFAULT_DB = DATA_HOME / "bvmac.db"
DEFAULT_FOLDER = DATA_HOME / "bulletins"
BASE_URL = "https://www.bvm-ac.org/wp-content/uploads"

