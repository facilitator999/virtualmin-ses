#!/bin/bash
# Uninstall virtualmin-ses plugin
# Usage: bash uninstall.sh

set -e

PLUGIN_NAME="virtualmin-ses"
WEBMIN_DIR="/usr/libexec/webmin"
PLUGIN_DIR="$WEBMIN_DIR/$PLUGIN_NAME"
CONFIG_DIR="/etc/webmin/$PLUGIN_NAME"

echo "=== Uninstalling $PLUGIN_NAME ==="

# Check we're root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root"
    exit 1
fi

# Confirm
read -p "This will disable SES routing for all domains. Continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Remove all domains from Postfix transport map
TRANSPORT_MAP="/etc/postfix/ses_relayhost_maps"
if [ -f "$TRANSPORT_MAP" ]; then
    echo "Removing all SES routing from Postfix..."
    echo "# Managed by virtualmin-ses plugin" > "$TRANSPORT_MAP"
    postmap "$TRANSPORT_MAP" 2>/dev/null || true
fi

# Restore original Postfix config if backup exists
POSTFIX_BACKUP="$CONFIG_DIR/backups/main.cf.pre-ses"
if [ -f "$POSTFIX_BACKUP" ]; then
    echo "Restoring original Postfix configuration..."
    cp "$POSTFIX_BACKUP" /etc/postfix/main.cf
    postfix reload 2>/dev/null || systemctl reload postfix 2>/dev/null || true
    echo "Postfix config restored from backup."
else
    echo "No Postfix backup found — current config preserved."
    # Just reload to pick up empty transport map
    postfix reload 2>/dev/null || systemctl reload postfix 2>/dev/null || true
fi

# Remove plugin files
if [ -d "$PLUGIN_DIR" ]; then
    echo "Removing plugin files..."
    rm -rf "$PLUGIN_DIR"
fi

# Remove from Webmin ACL
if [ -f "/etc/webmin/webmin.acl" ]; then
    sed -i "s/ $PLUGIN_NAME//" /etc/webmin/webmin.acl 2>/dev/null || true
fi

# Keep backups and state for safety
echo ""
echo "NOTE: DNS backups preserved at $CONFIG_DIR/backups/"
echo "NOTE: SES identities still exist in AWS — delete from AWS console if needed."
echo "NOTE: To fully clean up, run: rm -rf $CONFIG_DIR"

# Restart Webmin
echo "Restarting Webmin..."
systemctl restart webmin 2>/dev/null || /etc/init.d/webmin restart 2>/dev/null || true

echo ""
echo "=== Uninstall complete ==="
echo "SES identities still exist in AWS — delete from console if needed."
echo "DNS backups kept at $CONFIG_DIR/backups/ for safety."
