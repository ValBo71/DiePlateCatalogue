#!/bin/bash
# Printing Catalog Server - macOS launcher (self-installing)
# Double-click this file in Finder (or run `./run_mac.command` in Terminal).

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "Checking environment..."

# 0. Create a Desktop shortcut with a custom icon on first run
DESKTOP_APP="$HOME/Desktop/Printing Catalog.app"
ICON_SRC="$PROJECT_DIR/assets/icon.png"
if [ ! -d "$DESKTOP_APP" ] && [ -f "$ICON_SRC" ]; then
    set +e
    (
        set -e
        echo "Creating Desktop shortcut..."
        mkdir -p "$DESKTOP_APP/Contents/MacOS" "$DESKTOP_APP/Contents/Resources"

        ICONSET_DIR="$(mktemp -d)/AppIcon.iconset"
        mkdir -p "$ICONSET_DIR"
        for size in 16 32 128 256 512; do
            sips -z "$size" "$size" "$ICON_SRC" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
            double=$((size * 2))
            sips -z "$double" "$double" "$ICON_SRC" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
        done
        iconutil -c icns "$ICONSET_DIR" -o "$DESKTOP_APP/Contents/Resources/AppIcon.icns"
        rm -rf "$(dirname "$ICONSET_DIR")"

        cat > "$DESKTOP_APP/Contents/MacOS/launcher" <<LAUNCHER
#!/bin/bash
cd "$PROJECT_DIR"
exec ./run_mac.command
LAUNCHER
        chmod +x "$DESKTOP_APP/Contents/MacOS/launcher"

        cat > "$DESKTOP_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Printing Catalog</string>
    <key>CFBundleDisplayName</key>
    <string>Printing Catalog</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>local.printingcatalog.launcher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
</dict>
</plist>
PLIST
        touch "$DESKTOP_APP"
        echo "Desktop shortcut created: $DESKTOP_APP"
    )
    if [ $? -ne 0 ]; then
        echo "Warning: could not create the Desktop shortcut, continuing anyway..."
        rm -rf "$DESKTOP_APP"
    fi
    set -e
fi

PORTABLE_DIR="python_portable"
PORTABLE_BIN="$PORTABLE_DIR/bin/python3"
USE_VENV=1

# Returns success only if a real, working Python >= 3.8 runs. `command -v python3` alone
# is not enough: on a clean Mac /usr/bin/python3 is just the Xcode Command Line Tools stub,
# which pops up an install dialog and exits non-zero (and set -e would then abort silently).
system_python_works() {
    command -v python3 >/dev/null 2>&1 && \
        python3 -c 'import sys, venv; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

# 1. Prefer a working system Python 3 interpreter
if system_python_works; then
    PYTHON_BIN=python3
    echo "System Python found. Using system Python..."
elif [ -x "$PORTABLE_BIN" ]; then
    # 2. Reuse a previously downloaded portable Python
    PYTHON_BIN="$(pwd)/$PORTABLE_BIN"
    USE_VENV=0
    echo "Portable Python found. Using portable Python..."
else
    # 3. No system Python -> download a self-contained build (no admin rights needed)
    echo "System Python not found. Installing portable Python environment..."

    case "$(uname -m)" in
        arm64)  PBS_ARCH=aarch64 ;;
        x86_64) PBS_ARCH=x86_64 ;;
        *)
            echo "Error: Unsupported Mac architecture: $(uname -m)"
            read -p "Press Enter to close..."
            exit 1
            ;;
    esac

    echo "Looking up latest portable Python 3.11 build for macOS ($PBS_ARCH)..."
    RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest") || {
        echo "Error: Could not reach GitHub to look up the Python build. Check your internet connection."
        read -p "Press Enter to close..."
        exit 1
    }

    DOWNLOAD_URL=$(printf '%s' "$RELEASE_JSON" \
        | grep -o '"browser_download_url": *"[^"]*"' \
        | sed -E 's/"browser_download_url": *"([^"]*)"/\1/' \
        | grep "cpython-3\.11\." \
        | grep "${PBS_ARCH}-apple-darwin-install_only\.tar\.gz" \
        | head -n1)

    if [ -z "$DOWNLOAD_URL" ]; then
        echo "Error: Could not find a matching portable Python build."
        echo "Please install Python manually: brew install python"
        echo "or download it from https://www.python.org/downloads/macos/"
        read -p "Press Enter to close..."
        exit 1
    fi

    echo "Downloading portable Python..."
    curl -fsSL "$DOWNLOAD_URL" -o python_embed.tar.gz || {
        echo "Error: Failed to download portable Python!"
        read -p "Press Enter to close..."
        exit 1
    }

    echo "Extracting Python..."
    mkdir -p "$PORTABLE_DIR"
    tar -xzf python_embed.tar.gz -C "$PORTABLE_DIR" --strip-components=1
    rm -f python_embed.tar.gz

    PYTHON_BIN="$(pwd)/$PORTABLE_BIN"
    USE_VENV=0
fi
echo "Using $("$PYTHON_BIN" --version)"

# 4. Set up an isolated environment
if [ "$USE_VENV" -eq 1 ]; then
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        "$PYTHON_BIN" -m venv .venv
    fi
    echo "Activating virtual environment..."
    source .venv/bin/activate
    PYTHON_BIN=python
fi

# 5. Install/verify dependencies
echo "Installing/verifying dependencies..."
"$PYTHON_BIN" -m pip install --quiet --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt

# 6. Ensure required directories exist
mkdir -p database uploads

# Clear any leftover exit marker from a previous crashed run
rm -f database/.exit_requested

# 7. Start the server and open the browser
echo "Server is starting on http://localhost:5050 ..."
( sleep 1 && open "http://localhost:5050" ) &
# "|| ..." keeps set -e from closing the window when the app crashes, so the
# error stays readable and the prompt below is still shown.
"$PYTHON_BIN" app.py || echo "The server stopped with an error (exit code $?). See the messages above."

# The app's Exit button writes this marker just before shutting itself down, so
# we can close the window right away instead of waiting for Enter - a Ctrl+C or
# crash leaves no marker, so the prompt below still shows for those cases.
# (Whether the Terminal window itself then closes depends on your Terminal.app
# setting under Settings > Profiles > Shell > "When the shell exits".)
if [ -f database/.exit_requested ]; then
    rm -f database/.exit_requested
    exit 0
fi

read -p "Server stopped. Press Enter to close..."
