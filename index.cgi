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
my $health = ses_get_account_health();
if ($health->{'ok'}) {
    print &ui_table_start(undef, "width=100%", 4);

    # Connection status
    my $aws_status = "<span style='color:green'>&#10003;</span> AWS SES: Connected ($config{'aws_region'})";
    my $mode = $health->{'production'} ? 'Production' : "<span style='color:#856404'>$text{'health_sandbox'}</span>";
    print &ui_table_row(undef, "$aws_status &nbsp;|&nbsp; $mode", 2);

    # CF status
    my $cf_status = "";
    if ($config{'cf_api_token'}) {
        my $cf = cf_test_credentials();
        if ($cf->{'ok'}) {
            $cf_status = "<span style='color:green'>&#10003;</span> Cloudflare: Valid ($cf->{'zones'} zones)";
        } else {
            $cf_status = "<span style='color:red'>&#10007;</span> Cloudflare: $cf->{'error'}";
        }
    } else {
        $cf_status = "<span style='color:grey'>&#8212;</span> Cloudflare: Not configured";
    }

    # Sending stats
    my $sent = $health->{'sent24hr'} || 0;
    my $max = $health->{'max24hr'} || 0;
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
    if ($health->{'suspended'}) {
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
        my $ses_status = get_domain_ses_status($dom);
        my $provider = detect_mail_provider($dom);
        $status = "<span style='color:orange'>$text{'status_paused'}</span>";
        $status_msg = "<br><small>$text{'paused_msg'}</small>";
        @buttons = (
            "<a href='pause_domain.cgi?dom=$dom&action=resume'>$text{'btn_resume'}</a>",
            "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>"
        );
        print &ui_columns_row([
            "<b>$dom</b>$status_msg",
            $ses_status->{'ses'} ? $icon_yes : $icon_no,
            $ses_status->{'dkim'} eq 'SUCCESS' ? $icon_yes : ($ses_status->{'dkim'} eq 'PENDING' ? $icon_pending : $icon_no),
            $ses_status->{'spf'} ? $icon_yes : $icon_warn,
            $ses_status->{'dmarc'} ? $icon_yes : $icon_warn,
            $ses_status->{'cf'} ? $icon_yes : "<span style='color:grey'>&#10007;</span>",
            $provider,
            $status,
            join(" &nbsp; ", @buttons)
        ]);
    } else {
        # ENABLED state — check full status
        my $ses_status = get_domain_ses_status($dom);
        my $provider = detect_mail_provider($dom);

        my $ses_icon = $ses_status->{'ses'} ? $icon_yes : $icon_no;
        my $dkim_icon;
        if ($ses_status->{'dkim'} eq 'SUCCESS') {
            $dkim_icon = $icon_yes;
        } elsif ($ses_status->{'dkim'} eq 'PENDING') {
            $dkim_icon = $icon_pending;
        } else {
            $dkim_icon = "<span style='color:red'>&#10007;</span>";
        }
        my $spf_icon = $ses_status->{'spf'} ? $icon_yes : $icon_warn;
        my $dmarc_icon = $ses_status->{'dmarc'} ? $icon_yes : $icon_warn;
        my $cf_icon = $ses_status->{'cf'} ? $icon_yes : "<span style='color:grey'>&#10007;</span>";

        # Determine overall status
        my $overall;
        my $enabled_ts = $state->{'enabled_at'} || 0;
        my $elapsed = time() - $enabled_ts;

        if ($ses_status->{'dkim'} eq 'PENDING') {
            $overall = "<span style='color:orange'>$text{'status_pending'}</span>";
            my $hours = int($elapsed / 3600);
            my $time_str = $hours > 24 ? int($hours/24) . "d" : "${hours}h";
            $status_msg = "<br><small>" . &text('pending_msg', $time_str) . "</small>";
            @buttons = (
                "<a href='pause_domain.cgi?dom=$dom&action=pause'>$text{'btn_pause'}</a>",
                "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>",
                "<a href='index.cgi'>$text{'btn_recheck'}</a>"
            );
        } elsif ($ses_status->{'dkim'} eq 'SUCCESS' && $ses_status->{'spf'} && $ses_status->{'ses'}) {
            $overall = "<span style='color:green'><b>$text{'status_ready'}</b></span>";
            @buttons = (
                "<a href='pause_domain.cgi?dom=$dom&action=pause'>$text{'btn_pause'}</a>",
                "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>",
                "<a href='test_email.cgi?dom=$dom'>$text{'btn_test'}</a>",
                "<a href='view_backup.cgi?dom=$dom'>$text{'btn_backup'}</a>"
            );
        } elsif (!$ses_status->{'cf'}) {
            # Non-Cloudflare domain — manual DNS
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
