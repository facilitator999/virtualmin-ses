# Virtualmin SES — AWS SES Email Delivery Plugin

A Webmin/Virtualmin plugin that manages **AWS SES email delivery** and **Cloudflare DNS** for all your domains from a single dashboard. One-click enable per domain — automatically populates DKIM, SPF, and DMARC records in Cloudflare, configures Postfix routing, and validates everything. It's an all-in-one DNS validator and email delivery manager.

## What It Does

- **Automatic DNS population** — creates DKIM, SPF, and DMARC records in Cloudflare automatically, no manual record editing needed
- **All-in-one DNS validator** — dashboard shows DKIM, SPF, DMARC, and Cloudflare status for every domain at a glance, whether SES-enabled or not
- **Per-domain SES routing** — only enabled domains route through SES, everything else stays unchanged
- **DNS backup/restore** — backs up your DNS before making changes, restores on disable
- **Three states per domain**: Disabled (default), Enabled (routing through SES), Paused (keeps DNS/identity, stops routing)
- **Smart caching** — dashboard loads instantly from cache, refreshes every hour or on demand
- **Third-party email detection** — detects Google Workspace, Microsoft 365, Zoho, etc. via MX records
- **Bounce/complaint monitoring** — shows SES health metrics, warns before thresholds
- **Emergency disable** — one click removes all SES routing instantly
- **No AWS CLI needed** — pure Perl HTTP with AWS Signature V4 signing
- **SMTP credentials auto-derived** — no manual SMTP password entry needed

## Requirements

- **Webmin** with **Virtualmin** installed
- **Postfix** as your mail server
- **Rocky Linux / AlmaLinux / CentOS 8+** (should work on any Linux with Webmin)
- **Perl modules**: LWP::UserAgent, HTTP::Request, JSON, Digest::SHA, MIME::Base64, URI::Escape, Net::DNS (installer checks and installs these)

## What You Need Before Installing

1. **AWS Account** with SES in production mode (not sandbox)
2. **AWS IAM User** with `AmazonSESFullAccess` policy — you need the Access Key ID and Secret Access Key
3. **Cloudflare account** with your domains — you need an API Token with DNS edit permissions

## Installation

```bash
# Clone the repo
git clone https://github.com/facilitator999/virtualmin-ses.git /root/virtualmin-ses

# Install
cd /root/virtualmin-ses
bash install.sh
```

That's it. The installer:
- Checks all prerequisites (Perl modules, Postfix, Virtualmin)
- Installs missing Perl modules automatically
- Copies plugin files to Webmin
- Registers the module
- Restarts Webmin

## Setup (2 minutes)

1. Open **Webmin → Servers → AWS SES Email Delivery**
2. Click **Settings**
3. Enter your **AWS Access Key ID** and **Secret Access Key** (instructions are on the page)
4. Enter your **Cloudflare API Token** (instructions are on the page)
5. Click **Save Settings** — it tests both connections before saving

## Usage

### Enable SES for a domain
Click **Enable** next to any domain on the dashboard. The plugin will:
1. Back up existing DNS records
2. Create an SES identity in AWS
3. Push DKIM, SPF, and DMARC records to Cloudflare
4. Add the domain to Postfix's transport map
5. Disable OpenDKIM signing for that domain (SES handles DKIM)

DKIM verification takes 24-72 hours (sometimes faster). The domain shows as **PENDING** until verified, then turns **READY**.

### Pause a domain
Click **Pause** to stop routing through SES without losing the SES identity or DKIM verification. Click **Resume** to restore routing instantly — no waiting for DKIM again.

### Disable a domain
Click **Disable** to fully remove SES: deletes the identity, restores DNS from backup, removes from Postfix transport map.

### Non-Cloudflare domains
If a domain isn't on Cloudflare, the plugin shows you the exact DNS records to add manually, with a **Check DNS** button to verify propagation.

### Emergency Disable
Click **Emergency Disable All** to remove ALL SES routing instantly. SES identities and DNS are preserved — you can re-enable individual domains without waiting for DKIM re-verification.

## Dashboard

The dashboard shows:
- **SES account health** — sending quota, bounce rate, complaint rate with warnings
- **Per-domain status** — SES, DKIM, SPF, DMARC, Cloudflare status, mail provider detection
- **Contextual buttons** — different actions depending on each domain's state
- **Recent mail log** — last 10 entries for quick troubleshooting

## How It Works (Technical)

- Uses **`sender_dependent_relayhost_maps`** in Postfix — NOT a global relayhost
- Only SES-enabled domains route through SES; non-SES domains deliver directly
- System mail (root, cron) is unaffected
- DANE/DNSSEC preserved for direct-delivery domains
- SPF records are **merged**, not replaced — existing includes are kept
- MX records are **never touched**
- DMARC records are only created if none exist
- Existing third-party email (Google Workspace, Zoho, etc.) continues to work

## Updating

```bash
cd /root/virtualmin-ses
git pull
bash install.sh
```

Settings are preserved — only plugin code is updated.

## Uninstalling

```bash
cd /root/virtualmin-ses
bash uninstall.sh
```

This will:
- Remove all SES routing from Postfix
- Restore original Postfix config from backup
- Remove the plugin from Webmin
- **Keep** DNS backups (for safety)
- **Keep** SES identities in AWS (delete from AWS console if needed)

## File Structure

```
virtualmin-ses/
├── install.sh              # One-command installer
├── uninstall.sh            # One-command uninstaller
├── module.info             # Webmin module metadata
├── config                  # Default config (no secrets)
├── config.info             # Config form definitions
├── virtualmin-ses-lib.pl   # Core library (AWS SES API, Cloudflare API, DNS, Postfix)
├── index.cgi               # Dashboard
├── settings.cgi            # Settings page with inline help
├── settings_save.cgi       # Save settings
├── enable_domain.cgi       # Enable SES for a domain
├── disable_domain.cgi      # Disable SES for a domain
├── pause_domain.cgi        # Pause/Resume SES routing
├── fix_domain.cgi          # Auto-fix domain issues
├── test_email.cgi          # Send test email
├── view_log.cgi            # Mail log viewer
├── view_backup.cgi         # DNS backup viewer with diff
├── emergency.cgi           # Emergency disable all
├── acl_security.pl         # Access control (root only)
├── lang/en                 # English language strings
└── images/icon.png         # Module icon
```

## Security

- AWS credentials stored in Webmin module config (root-readable only)
- SMTP password auto-derived from IAM key (never entered manually)
- `/etc/postfix/sasl_passwd` is chmod 600
- Module is root-only access
- No secrets in the git repo

## License

MIT
