"""Stand-in for the ``rtk`` binary in tests: ``fake_rtk.py rewrite <command>``.

Mirrors RTK's contract: exit 3 and print ``rtk <command>`` for commands it knows, exit 1 and
print nothing otherwise.
"""

import sys

KNOWN = ("git", "ls", "grep", "find", "pytest", "npm", "cat")

if sys.argv[1:2] == ["rewrite"] and len(sys.argv) > 2 and sys.argv[2].split()[0] in KNOWN:
    print(f"rtk {sys.argv[2]}")
    sys.exit(3)
sys.exit(1)
