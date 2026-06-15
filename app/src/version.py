"""
Single source of truth for app version + product metadata.

Importing this module is cheap and pulls no third-party deps. Bumped
manually for each release; the Inno Setup script and PyInstaller spec
read it via simple regex, and `app_main.py --version` returns it.
"""

__version__ = "1.0.0"
__version_info__ = (1, 0, 0)
__app_name__ = "Photo Organizer"
__app_id__ = "PhotoOrganizer"
__publisher__ = "Photo Organizer Project"
__copyright__ = "Copyright (c) 2026 Photo Organizer Project"
__license__ = "MIT"
__homepage__ = "https://github.com/DharuneshBoopathy/PhotoOrganizer"
__bug_tracker__ = "https://github.com/DharuneshBoopathy/PhotoOrganizer/issues"


def banner() -> str:
    return f"{__app_name__} {__version__}"
