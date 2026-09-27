"""PyInstaller entry point that preserves package-relative imports."""
from study_archive_prep.app import main


if __name__ == "__main__":
    raise SystemExit(main())
