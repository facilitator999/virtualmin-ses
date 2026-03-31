#!/usr/bin/perl
# Main dashboard for AWS SES Email Delivery plugin

require './virtualmin-ses-lib.pl';
&ReadParse();

ui_print_header(undef, $text{'index_title'}, "", undef, 1, 1);

# Check if AWS credentials configured
if (!$config{'aws_access_key'} || !$config{'aws_secret_key'}) {
    print "<p>$text{'index_noconfig'}</p>";
    print &ui_link("settings.cgi", $text{'index_settings'});
    ui_print_footer("/", $text{'index_title'});
    exit;
}

# Top bar: links
print "<div style='margin-bottom:10px'>";
print &ui_link("settings.cgi", $text{'index_settings'});
print " &nbsp; | &nbsp; ";
print &ui_link("view_log.cgi", $text{'log_title'});
print "</div>";

# Health status bar
my ($health, $health_err) = ses_get_account_health();
if ($health && !$health_err) {
    print &ui_table_start(undef, "width=100%", 4);

    # Connection status
    my $aws_status = "<span style='color:green'>&#10003;</span> AWS SES: Connected ($config{'aws_region'})";
    my $mode = $health->{'sandbox'} ? "<span style='color:#856404'>$text{'health_sandbox'}</span>" : 'Production';
    print &ui_table_row(undef, "$aws_status &nbsp;|&nbsp; $mode", 2);

    # CF status
    my $cf_status = "";
    if ($config{'cf_api_token'}) {
        my ($cf_ok, $cf_err, $cf_zones) = cf_test_credentials();
        if ($cf_ok && !$cf_err) {
            $cf_status = "<span style='color:green'>&#10003;</span> Cloudflare: Valid ($cf_zones zones)";
        } else {
            $cf_status = "<span style='color:red'>&#10007;</span> Cloudflare: $cf_err";
        }
    } else {
        $cf_status = "<span style='color:grey'>&#8212;</span> Cloudflare: Not configured";
    }

    # Sending stats
    my $sent = $health->{'sent_24h'} || 0;
    my $max = $health->{'max_24h'} || 0;
    my $sending = "Sending: $sent/$max today";
    print &ui_table_row(undef, "$cf_status &nbsp;|&nbsp; $sending", 2);

    # Bounce and complaint rates
    my $bounce = $health->{'bounce_rate'} || 0;
    my $complaint = $health->{'complaint_rate'} || 0;

    my $bounce_color = 'green';
    $bounce_color = 'orange' if $bounce >= 3;
    $bounce_color = 'red' if $bounce >= 4.5;

    my $comp_color = 'green';
    $comp_color = 'orange' if $complaint >= 0.05;
    $comp_color = 'red' if $complaint >= 0.08;

    my $bounce_str = sprintf("$text{'health_bounce'}: <span style='color:%s'>%.1f%%</span>", $bounce_color, $bounce);
    my $comp_str = sprintf("$text{'health_complaint'}: <span style='color:%s'>%.2f%%</span>", $comp_color, $complaint);
    print &ui_table_row(undef, "$bounce_str &nbsp;|&nbsp; $comp_str", 2);

    print &ui_table_end();

    # Warnings
    if (!$health->{'sending_enabled'}) {
        print "<div style='background:#f8d7da;color:#721c24;padding:10px;border-radius:4px;margin:10px 0'>";
        print "<b>$text{'health_alert_suspended'}</b></div>";
    }
    if ($bounce >= 3 && !$health->{'suspended'}) {
        print "<div style='background:#fff3cd;color:#856404;padding:8px;border-radius:4px;margin:5px 0'>";
        print "$text{'health_warn_bounce'}</div>";
    }
    if ($complaint >= 0.05 && !$health->{'suspended'}) {
        print "<div style='background:#fff3cd;color:#856404;padding:8px;border-radius:4px;margin:5px 0'>";
        print "$text{'health_warn_complaint'}</div>";
    }
}

# Emergency button
print "<div style='text-align:right;margin:10px 0'>";
print "<a href='emergency.cgi' style='color:red;font-weight:bold'>$text{'index_emergency'}</a>";
print " &mdash; <small>$text{'index_emergency_desc'}</small>";
print "</div>";

# Get all Virtualmin domains
my @domains = get_virtualmin_domains();

# Domain table
print &ui_columns_start([
    $text{'domain_col'},
    $text{'ses_col'},
    $text{'dkim_col'},
    $text{'spf_col'},
    $text{'dmarc_col'},
    $text{'cf_col'},
    $text{'provider_col'},
    $text{'status_col'},
    ""
], 100);

foreach my $dom (sort @domains) {
    my $state = get_domain_state($dom);
    my $status;
    my @buttons;
    my $status_msg = "";

    my $icon_yes = "<span style='color:green'>&#10003;</span>";
    my $icon_no = "<span style='color:grey'>&#8212;</span>";
    my $icon_pending = "<span style='color:orange'>&#9203;</span>";
    my $icon_warn = "<span style='color:orange'>&#63;</span>";

    if (!$state || !$state->{'enabled'}) {
        # DISABLED state
        my ($ses_col, $dkim_col, $spf_col, $dmarc_col, $cf_col) = ($icon_no, $icon_no, $icon_no, $icon_no, $icon_no);
        my $provider = detect_mail_provider($dom);
        $status = "<span style='color:grey'>$text{'status_disabled'}</span>";
        @buttons = ("<a href='enable_domain.cgi?dom=$dom'>$text{'btn_enable'}</a>");
        print &ui_columns_row([
            "<b>$dom</b>",
            $ses_col, $dkim_col, $spf_col, $dmarc_col, $cf_col,
            $provider,
            $status,
            join(" &nbsp; ", @buttons)
        ]);
    } elsif ($state->{'paused'}) {
        # PAUSED state
        my $s = get_domain_ses_status($dom);
        my $provider = $s->{'mail_provider'} || detect_mail_provider($dom);
        $status = "<span style='color:orange'>$text{'status_paused'}</span>";
        $status_msg = "<br><small>$text{'paused_msg'}</small>";
        @buttons = (
            "<a href='pause_domain.cgi?dom=$dom&action=resume'>$text{'btn_resume'}</a>",
            "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>"
        );
        my $dkim_s = $s->{'dkim_status'} || '';
        print &ui_columns_row([
            "<b>$dom</b>$status_msg",
            $s->{'ses_exists'} ? $icon_yes : $icon_no,
            $dkim_s eq 'SUCCESS' ? $icon_yes : ($dkim_s eq 'PENDING' ? $icon_pending : $icon_no),
            $s->{'spf_ok'} ? $icon_yes : $icon_warn,
            $s->{'dmarc_ok'} ? $icon_yes : $icon_warn,
            $s->{'on_cloudflare'} ? $icon_yes : "<span style='color:grey'>&#10007;</span>",
            $provider,
            $status,
            join(" &nbsp; ", @buttons)
        ]);
    } else {
        # ENABLED state — check full status
        my $s = get_domain_ses_status($dom);
        my $provider = $s->{'mail_provider'} || detect_mail_provider($dom);
        my $dkim_s = $s->{'dkim_status'} || '';

        my $ses_icon = $s->{'ses_exists'} ? $icon_yes : $icon_no;
        my $dkim_icon;
        if ($dkim_s eq 'SUCCESS') {
            $dkim_icon = $icon_yes;
        } elsif ($dkim_s eq 'PENDING') {
            $dkim_icon = $icon_pending;
        } else {
            $dkim_icon = "<span style='color:red'>&#10007;</span>";
        }
        my $spf_icon = $s->{'spf_ok'} ? $icon_yes : $icon_warn;
        my $dmarc_icon = $s->{'dmarc_ok'} ? $icon_yes : $icon_warn;
        my $cf_icon = $s->{'on_cloudflare'} ? $icon_yes : "<span style='color:grey'>&#10007;</span>";

        # Use overall from status check
        my $overall_status = $s->{'overall'} || 'UNKNOWN';
        my $overall;
        my $enabled_ts = $state->{'enabled_at'} || 0;
        my $elapsed = time() - $enabled_ts;

        if ($overall_status eq 'PENDING') {
            $overall = "<span style='color:orange'>$text{'status_pending'}</span>";
            my $hours = int($elapsed / 3600);
            my $time_str = $hours > 24 ? int($hours/24) . "d" : "${hours}h";
            $status_msg = "<br><small>" . &text('pending_msg', $time_str) . "</small>";
            @buttons = (
                "<a href='pause_domain.cgi?dom=$dom&action=pause'>$text{'btn_pause'}</a>",
                "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>",
                "<a href='index.cgi'>$text{'btn_recheck'}</a>"
            );
        } elsif ($overall_status eq 'READY') {
            $overall = "<span style='color:green'><b>$text{'status_ready'}</b></span>";
            @buttons = (
                "<a href='pause_domain.cgi?dom=$dom&action=pause'>$text{'btn_pause'}</a>",
                "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>",
                "<a href='test_email.cgi?dom=$dom'>$text{'btn_test'}</a>",
                "<a href='view_backup.cgi?dom=$dom'>$text{'btn_backup'}</a>"
            );
        } elsif ($overall_status eq 'MANUAL_DNS') {
            my $dns_prov = get_dns_provider($dom);
            $overall = "<span style='color:#856404'>$text{'status_manual'}</span>";
            $status_msg = "<br><small>" . &text('manual_msg', $dns_prov) . "</small>";
            @buttons = (
                "<a href='fix_domain.cgi?dom=$dom&action=showrecords'>$text{'btn_showrecords'}</a>",
                "<a href='fix_domain.cgi?dom=$dom&action=checkdns'>$text{'btn_checkdns'}</a>",
                "<a href='pause_domain.cgi?dom=$dom&action=pause'>$text{'btn_pause'}</a>",
                "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>"
            );
        } else {
            $overall = "<span style='color:red'>$text{'status_attention'}</span>";
            my $issues_str = join(", ", @{$s->{'issues'} || []});
            $status_msg = "<br><small>$issues_str</small>" if $issues_str;
            @buttons = (
                "<a href='fix_domain.cgi?dom=$dom'>$text{'btn_fix'}</a>",
                "<a href='pause_domain.cgi?dom=$dom&action=pause'>$text{'btn_pause'}</a>",
                "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>"
            );
        }

        print &ui_columns_row([
            "<b>$dom</b>$status_msg",
            $ses_icon, $dkim_icon, $spf_icon, $dmarc_icon, $cf_icon,
            $provider,
            $overall,
            join(" &nbsp; ", @buttons)
        ]);
    }
}

print &ui_columns_end();

# Recent mail log
print "<br>";
print &ui_table_start("$text{'log_title'} &nbsp; <small><a href='view_log.cgi'>$text{'log_recent'}</a></small>", "width=100%", 1);
my @log = get_recent_mail_log(undef, 10);
if (@log) {
    my $log_html = "<pre style='margin:0;font-size:12px'>";
    foreach my $entry (@log) {
        $log_html .= &html_escape($entry) . "\n";
    }
    $log_html .= "</pre>";
    print &ui_table_row(undef, $log_html);
} else {
    print &ui_table_row(undef, "<i>No recent entries</i>");
}
print &ui_table_end();

ui_print_footer("/", $text{'index_title'});
