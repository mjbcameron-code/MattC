#!/bin/bash
# Double-click this in Finder to run the whole weekly cycle and open the ledger.
#
# macOS treats a .command file as launchable: it opens Terminal, runs this, and
# leaves the window up so you can read what happened. Nothing to install.
cd "$(dirname "$0")" || exit 1

printf '\n  The Value Ledger\n  ================\n\n'

if ! command -v python3 >/dev/null 2>&1; then
    echo "  Python 3 is not installed. Install it from python.org, then try again."
    echo
    read -r -p "  Press return to close. "
    exit 1
fi

python3 -m vb weekly "$@"
STATUS=$?

echo
if [ $STATUS -eq 0 ]; then
    echo "  Done. The dashboard should have opened in your browser."
else
    echo "  Something went wrong — the message above says what."
    echo "  Running 'python3 -m vb doctor' will usually explain it."
fi
echo
read -r -p "  Press return to close this window. "
