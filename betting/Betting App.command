#!/bin/bash
# Double-click to open the Value Ledger in your browser.
# Leave the Terminal window that opens running while you use it; closing it
# stops the app. Press Control-C in that window to stop it deliberately.
cd "$(dirname "$0")" || exit 1
python3 -m vb app || {
    echo
    echo "  Could not start. If it mentions Flask, run this once:"
    echo "      pip3 install -r requirements.txt"
    echo
    read -r -p "  Press return to close. "
}
