"""PyInstaller entry point."""
import sys

from pdfmerger.app import main

if __name__ == "__main__":
    sys.exit(main())
