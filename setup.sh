#!/bin/bash
# ISRC Fetcher - Mac setup

echo ""
echo " =============================================="
echo "  ISRC Fetcher - One-time Setup"
echo " =============================================="
echo ""

# --- Check/install Python ---
if ! command -v python3 &>/dev/null; then
    echo " Python not found. Installing via Homebrew..."
    echo ""

    if ! command -v brew &>/dev/null; then
        echo " Installing Homebrew first..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for this session (Apple Silicon)
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
    fi

    brew install python3
fi

echo " Python found: $(python3 --version)"
echo ""

# --- Install packages ---
echo " Installing required packages..."
pip3 install --quiet openpyxl requests
echo " Packages installed."
echo ""

# --- Create launcher script ---
LAUNCHER="$HOME/Desktop/Start ISRC Fetcher.command"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat > "$LAUNCHER" <<EOF
#!/bin/bash
cd "$SCRIPT_DIR"
python3 app.py
EOF
chmod +x "$LAUNCHER"

echo " Desktop launcher created: 'Start ISRC Fetcher.command'"
echo ""
echo " =============================================="
echo "  Setup complete!"
echo " =============================================="
echo ""
echo " To start the app:"
echo "   Double-click 'Start ISRC Fetcher.command' on your Desktop"
echo ""
