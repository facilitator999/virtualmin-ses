#!/usr/bin/perl
# Settings page for AWS SES Email Delivery plugin

require './virtualmin-ses-lib.pl';
&ReadParse();

ui_print_header(undef, $text{'settings_title'}, "", undef, 1, 1);

# Current config
my %c = %config;

# Test AWS if credentials exist
my ($aws_ok, $aws_msg, $ses_status, $ses_quota, $ses_rate, $ses_sandbox);
if ($c{'aws_access_key'} && $c{'aws_secret_key'}) {
    my ($data, $err) = ses_test_credentials();
    if (!$err && $data) {
        $aws_ok = 1;
        $ses_status = $data->{'ProductionAccessEnabled'} ? 'Production' : 'Sandbox';
        $ses_sandbox = !$data->{'ProductionAccessEnabled'};
        if ($data->{'SendQuota'}) {
            $ses_quota = $data->{'SendQuota'}{'Max24HourSend'} || 'Unknown';
            $ses_rate = $data->{'SendQuota'}{'MaxSendRate'} || 'Unknown';
        }
        $aws_msg = "Connected ($c{'aws_region'})";
    } else {
        $aws_ok = 0;
        $aws_msg = $err || 'Connection failed';
    }
}

# Test Cloudflare if token exists
my ($cf_ok, $cf_msg, $cf_zones, $cf_expiry);
if ($c{'cf_api_token'}) {
    my ($ok, $err, $zones) = cf_test_credentials();
    if ($ok && !$err) {
        $cf_ok = 1;
        $cf_zones = $zones || 0;
        $cf_expiry = 'Never';
        $cf_msg = "Valid";
    } else {
        $cf_ok = 0;
        $cf_msg = $err || 'Connection failed';
    }
}

# Postfix status
my $pf_status = get_postfix_ses_status();

# Begin form
print &ui_form_start("settings_save.cgi", "post");

# AWS SES section
print &ui_table_start($text{'settings_aws_header'}, "width=100%", 2);

# Inline help for getting AWS credentials
my $aws_help = <<'HTML';
<div style="background:#e8f4fd;border:1px solid #bee5eb;border-radius:4px;padding:10px;margin-bottom:10px;font-size:13px;color:#0c5460">
<b>How to get these credentials:</b><br>
1. Log into <a href="https://console.aws.amazon.com/iam/" target="_blank">AWS Console &rarr; IAM</a><br>
2. Left sidebar &rarr; <b>Users</b> &rarr; <b>Create user</b><br>
3. Name it <code>virtualmin-ses</code> &rarr; Next<br>
4. Select <b>Attach policies directly</b> &rarr; search <code>AmazonSESFullAccess</code> &rarr; tick it &rarr; Create user<br>
5. Click the new user &rarr; <b>Security credentials</b> tab &rarr; <b>Create access key</b><br>
6. Choose <b>Application running outside AWS</b> &rarr; Create<br>
7. Copy both the <b>Access Key ID</b> (starts with AKIA...) and <b>Secret Access Key</b> below<br>
<i>Note: The Secret Key is only shown once — save it somewhere safe.</i>
</div>
HTML
print &ui_table_row(undef, $aws_help, 2);

print &ui_table_row($text{'settings_aws_key'},
    &ui_textbox("aws_access_key", $c{'aws_access_key'}, 40) .
    " <small style='color:#666'>Starts with AKIA...</small>");

print &ui_table_row($text{'settings_aws_secret'},
    &ui_textbox("aws_secret_key", $c{'aws_secret_key'}, 50, 0, undef, "type=password") .
    " <small style='color:#666'>Shown only once when created</small>");

my @regions = ('us-east-1', 'us-west-2', 'eu-west-1', 'eu-central-1', 'ap-south-1', 'ap-southeast-2');
print &ui_table_row($text{'settings_aws_region'},
    &ui_select("aws_region", $c{'aws_region'}, \@regions) .
    " <small style='color:#666'>Must match the region where SES is set up</small>");

if ($c{'aws_access_key'} && $c{'aws_secret_key'}) {
    my $status_icon = $aws_ok ? "<span style='color:green'>&#10003;</span>" : "<span style='color:red'>&#10007;</span>";
    print &ui_table_row($text{'settings_aws_test'}, "$status_icon $aws_msg");

    if ($aws_ok) {
        print &ui_table_row($text{'settings_aws_smtp'},
            "<span style='color:green'>&#10003;</span> $text{'settings_aws_smtp'}");
        print &ui_table_row($text{'settings_aws_status'}, $ses_status);
        print &ui_table_row($text{'settings_aws_quota'}, "${ses_quota}/day &nbsp; Rate: ${ses_rate}/second");
    }
}

print &ui_table_end();

# Cloudflare section
print &ui_table_start($text{'settings_cf_header'}, "width=100%", 2);

my $cf_help = <<'HTML';
<div style="background:#e8f4fd;border:1px solid #bee5eb;border-radius:4px;padding:10px;margin-bottom:10px;font-size:13px;color:#0c5460">
<b>How to get a Cloudflare API Token:</b><br>
1. Log into <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank">Cloudflare &rarr; My Profile &rarr; API Tokens</a><br>
2. Click <b>Create Token</b><br>
3. Use the <b>Edit zone DNS</b> template<br>
4. Under Zone Resources, select <b>All zones</b> (or pick specific ones)<br>
5. Click <b>Continue to summary</b> &rarr; <b>Create Token</b><br>
6. Copy the token and paste it below<br>
<i>Note: The token needs DNS edit permissions for all zones you want to manage.</i>
</div>
HTML
print &ui_table_row(undef, $cf_help, 2);

print &ui_table_row($text{'settings_cf_token'},
    &ui_textbox("cf_api_token", $c{'cf_api_token'}, 50, 0, undef, "type=password"));

if ($c{'cf_api_token'}) {
    my $status_icon = $cf_ok ? "<span style='color:green'>&#10003;</span>" : "<span style='color:red'>&#10007;</span>";
    print &ui_table_row($text{'settings_cf_test'}, "$status_icon $cf_msg");
    if ($cf_ok) {
        print &ui_table_row($text{'settings_cf_zones'}, $cf_zones);
        print &ui_table_row($text{'settings_cf_expiry'}, $cf_expiry);
    }
}

print &ui_table_end();

# Email defaults section
print &ui_table_start($text{'settings_defaults_header'}, "width=100%", 2);

my $defaults_help = <<'HTML';
<div style="background:#f0f0f0;border:1px solid #ddd;border-radius:4px;padding:10px;margin-bottom:10px;font-size:13px;color:#555">
These defaults are used when enabling SES for a domain. You usually don't need to change them.
SPF tells email providers that Amazon is authorised to send on your behalf.
DMARC tells providers what to do with emails that fail authentication checks.
</div>
HTML
print &ui_table_row(undef, $defaults_help, 2);

print &ui_table_row($text{'settings_spf'},
    &ui_textbox("spf_include", $c{'spf_include'} || 'amazonses.com', 30) .
    " <small style='color:#666'>Leave as default unless told otherwise</small>");

my @policies = (['none', 'none - Monitoring only'],
                ['quarantine', 'quarantine - Mark suspicious'],
                ['reject', 'reject - Block failures']);
print &ui_table_row($text{'settings_dmarc_policy'},
    &ui_select("dmarc_policy", $c{'dmarc_policy'} || 'none',
        [map { [$_->[0], $_->[1]] } @policies]));

print &ui_table_row($text{'settings_dmarc_rua'},
    &ui_textbox("dmarc_rua", $c{'dmarc_rua'}, 40) .
    " <small style='color:#666'>e.g. dmarc-reports\@yourdomain.com — leave blank to skip</small>");

my $server_ip = get_server_ip();
print &ui_table_row($text{'settings_server_ip'}, $server_ip);

print &ui_table_end();

# Postfix relay status section
print &ui_table_start($text{'settings_postfix_header'}, "width=100%", 2);

my $icon_ok = "<span style='color:green'>&#10003;</span>";
my $icon_warn = "<span style='color:orange'>&#9888;</span>";
my $icon_no = "<span style='color:grey'>&#8212;</span>";

print &ui_table_row($text{'settings_postfix_routing'},
    ($pf_status->{'routing_configured'} ? "$icon_ok Configured (sender_dependent_relayhost_maps)" : "$icon_no Not configured"));

print &ui_table_row($text{'settings_postfix_sasl'},
    ($pf_status->{'sasl_configured'} ? "$icon_ok Configured" : "$icon_no Not configured"));

print &ui_table_row($text{'settings_postfix_tls'},
    ($pf_status->{'tls_level'} ? "$icon_ok Configured ($pf_status->{'tls_level'})" : "$icon_no Not configured"));

print &ui_table_row($text{'settings_postfix_dane'},
    ($pf_status->{'dane_preserved'} ? "$icon_ok Preserved for direct delivery" : "$icon_no Not configured"));

# Check OpenDKIM
my $dkim_active = -f '/etc/opendkim.conf' ? 1 : 0;
print &ui_table_row($text{'settings_postfix_dkim'},
    ($dkim_active ? "$icon_warn Active — will be disabled per-domain when SES enabled" : "$icon_no Not installed"));

# Backup status
my $backup_file = "/etc/webmin/virtualmin-ses/backups/main.cf.pre-ses";
print &ui_table_row($text{'settings_postfix_backup'},
    (-f $backup_file ? "$icon_ok $backup_file" : "$icon_no No backup yet"));

# Postfix config buttons
my $pf_buttons = "";
$pf_buttons .= &ui_submit($text{'settings_postfix_reconfig'}, "reconfig_postfix") . " ";
if (-f $backup_file) {
    $pf_buttons .= &ui_submit($text{'settings_postfix_restore'}, "restore_postfix");
}
print &ui_table_row("", $pf_buttons) if $pf_buttons;

print &ui_table_end();

# SES sandbox warning
if ($ses_sandbox) {
    print &ui_table_start($text{'settings_sandbox_header'}, "width=100%", 1);
    print &ui_table_row(undef,
        "<p style='color:#856404;background:#fff3cd;padding:10px;border-radius:4px'>" .
        "<b>$icon_warn $text{'settings_sandbox_warn'}</b><br>" .
        "$text{'settings_sandbox_request'}</p>");

    my $template = "We run a Virtualmin server hosting WordPress websites. Email is " .
        "used for: transactional emails (contact forms, password resets, " .
        "order confirmations), and occasional newsletters via opt-in lists. " .
        "We handle bounces via SES SNS notifications. Expected volume: " .
        "500-2000 emails/day. All recipients have opted in.";
    print &ui_table_row(undef,
        "<b>$text{'settings_sandbox_template'}</b><br>" .
        "<textarea rows=5 cols=80 readonly onclick='this.select()'>$template</textarea>");
    print &ui_table_end();
}

# Save button
print &ui_form_end([[undef, $text{'settings_save'}]]);

ui_print_footer("index.cgi", $text{'index_title'});
