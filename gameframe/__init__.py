"""Game-independent runtime. Importing this package never attaches a device."""

import sys

# Indexed gamepacks are immutable; Python bytecode must not change their trees.
sys.dont_write_bytecode = True

API_VERSION = 1
