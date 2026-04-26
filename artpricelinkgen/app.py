"""Tkinter application entry point.

The original UI currently lives in artprice_link_generator.py. The domain logic has
been split into focused modules first, and this wrapper gives PyCharm a cleaner
place to import the App from while the UI class is migrated incrementally.
"""

from artpricelinkgen.artprice_link_generator import App

__all__ = ["App"]
