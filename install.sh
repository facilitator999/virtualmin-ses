#!/bin/bash
# Install virtualmin-ses plugin for Webmin/Virtualmin
# Usage: bash install.sh

set -e

PLUGIN_NAME="virtualmin-ses"
WEBMIN_DIR="/usr/libexec/webmin"
PLUGIN_DIR="$WEBMIN_DIR/$PLUGIN_NAME"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="/etc/webmin/$PLUGIN_NAME"
BACKUP_DIR="$CONFIG_DIR/backups"
STATE_DIR="$CONFIG_DIR/state"

echo "=== Installing $PLUGIN_NAME ==="

# Check we're root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root"
    exit 1
fi

# Check Webmin exists
if [ ! -d "$WEBMIN_DIR" ]; then
    echo "ERROR: Webmin not found at $WEBMIN_DIR"
    exit 1
fi

# Check Virtualmin
if [ ! -d "$WEBMIN_DIR/virtual-server" ]; then
    echo "ERROR: Virtualmin (virtual-server) module not found"
    exit 1
fi

# Check Postfix
if ! command -v postfix &>/dev/null; then
    echo "ERROR: Postfix not installed"
    exit 1
fi

# Check Perl modules
echo "Checking Perl dependencies..."
MISSING=""
for MOD in LWP::UserAgent HTTP::Request JSON URI::Escape Digest::SHA MIME::Base64 Net::DNS; do
    if ! perl -M"$MOD" -e1 2>/dev/null; then
        MISSING="$MISSING $MOD"
    fi
done

if [ -n "$MISSING" ]; then
    echo "Missing Perl modules:$MISSING"
    echo "Installing via dnf..."
    # Map Perl modules to RPM packages
    for MOD in $MISSING; do
        case $MOD in
            LWP::UserAgent)  dnf install -y perl-libwww-perl 2>/dev/null || dnf install -y perl-LWP-Protocol-https 2>/dev/null ;;
            HTTP::Request)   dnf install -y perl-HTTP-Message 2>/dev/null ;;
            JSON)            dnf install -y perl-JSON 2>/dev/null ;;
            URI::Escape)     dnf install -y perl-URI 2>/dev/null ;;
            Digest::SHA)     dnf install -y perl-Digest-SHA 2>/dev/null ;;
            MIME::Base64)    dnf install -y perl-MIME-Base64 2>/dev/null ;;
            Net::DNS)        dnf install -y perl-Net-DNS 2>/dev/null ;;
        esac
    done

    # Verify again
    for MOD in $MISSING; do
        if ! perl -M"$MOD" -e1 2>/dev/null; then
            echo "ERROR: Failed to install $MOD"
            exit 1
        fi
    done
    echo "All Perl dependencies installed."
fi

# Create plugin directory
echo "Copying plugin files..."
mkdir -p "$PLUGIN_DIR"
mkdir -p "$PLUGIN_DIR/images"
mkdir -p "$PLUGIN_DIR/lang"

# Copy files
cp "$SOURCE_DIR/module.info" "$PLUGIN_DIR/"
cp "$SOURCE_DIR/virtualmin-ses-lib.pl" "$PLUGIN_DIR/"
cp "$SOURCE_DIR/acl_security.pl" "$PLUGIN_DIR/"
cp "$SOURCE_DIR/config.info" "$PLUGIN_DIR/"
cp "$SOURCE_DIR/lang/en" "$PLUGIN_DIR/lang/"

# Copy CGI files and set executable
for CGI in index.cgi settings.cgi settings_save.cgi enable_domain.cgi disable_domain.cgi \
           pause_domain.cgi fix_domain.cgi test_email.cgi view_log.cgi view_backup.cgi emergency.cgi; do
    if [ -f "$SOURCE_DIR/$CGI" ]; then
        cp "$SOURCE_DIR/$CGI" "$PLUGIN_DIR/"
        chmod 755 "$PLUGIN_DIR/$CGI"
    else
        echo "WARNING: $CGI not found in source directory"
    fi
done

# Copy icon if exists
if [ -f "$SOURCE_DIR/images/icon.png" ]; then
    cp "$SOURCE_DIR/images/icon.png" "$PLUGIN_DIR/images/"
elif [ -f "$SOURCE_DIR/images/icon.gif" ]; then
    cp "$SOURCE_DIR/images/icon.gif" "$PLUGIN_DIR/images/"
fi

# Set permissions
chmod 644 "$PLUGIN_DIR/module.info"
chmod 644 "$PLUGIN_DIR/virtualmin-ses-lib.pl"
chmod 644 "$PLUGIN_DIR/acl_security.pl"
chmod 644 "$PLUGIN_DIR/config.info"
chmod 644 "$PLUGIN_DIR/lang/en"

# Create config directory
mkdir -p "$CONFIG_DIR"
mkdir -p "$BACKUP_DIR"
mkdir -p "$STATE_DIR"
chmod 700 "$CONFIG_DIR"

# Copy default config if not exists (preserve existing settings on upgrade)
if [ ! -f "$CONFIG_DIR/config" ]; then
    cp "$SOURCE_DIR/config" "$CONFIG_DIR/config"
    chmod 600 "$CONFIG_DIR/config"
    echo "Default config created."
else
    echo "Existing config preserved."
fi

# Register module with Webmin
echo "Registering module..."
# Webmin auto-detects modules in the module directory via module.info
# Just need to refresh the module list
if [ -f "/etc/webmin/webmin.acl" ]; then
    # Add to root user's allowed modules if not already there
    if ! grep -q "$PLUGIN_NAME" /etc/webmin/webmin.acl 2>/dev/null; then
        sed -i "s/^root:.*/& $PLUGIN_NAME/" /etc/webmin/webmin.acl 2>/dev/null || true
    fi
fi

# Restart Webmin to pick up new module
echo "Restarting Webmin..."
systemctl restart webmin 2>/dev/null || /etc/init.d/webmin restart 2>/dev/null || true

echo ""
echo "=== Installation complete ==="
echo "Open Webmin -> Servers -> AWS SES Email Delivery"
echo ""
echo "Next steps:"
echo "  1. Go to Settings and enter your AWS Access Key + Secret Key"
echo "  2. Enter your Cloudflare API Token"
echo "  3. Click [Test] to verify both connections"
echo "  4. Enable SES for domains from the dashboard"
