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

# Decide whether to use cache or fetch fresh
my $force_refresh = $in{'refresh'} ? 1 : 0;
my $cache = $force_refresh ? undef : get_dashboard_cache();
my $from_cache = defined($cache) ? 1 : 0;

if (!$from_cache) {
    $cache = fetch_dashboard_data();
    save_dashboard_cache($cache);
}

# Top bar: links + cache status
print "<div style='margin-bottom:10px'>";
print &ui_link("settings.cgi", $text{'index_settings'});
print " &nbsp; | &nbsp; ";
print &ui_link("view_log.cgi", $text{'log_title'});
print " &nbsp; | &nbsp; ";
if ($from_cache) {
    my $age_min = int(($cache->{'cache_age'} || 0) / 60);
    my $age_str = $age_min < 1 ? "less than a minute" : "${age_min} min";
    print "<small style='color:#666'>Cached $age_str ago</small> &nbsp;";
}
print "<a href='index.cgi?refresh=1'><b>Refresh Now</b></a>";
print "</div>";

# Health status bar
my $health = $cache->{'health'};
if ($health && !$health->{'error'}) {
    print &ui_table_start(undef, "width=100%", 4);

    # Connection status
    my $aws_status = "<span style='color:green'>&#10003;</span> AWS SES: Connected ($config{'aws_region'})";
    my $mode = $health->{'sandbox'} ? "<span style='color:#856404'>$text{'health_sandbox'}</span>" : 'Production';
    print &ui_table_row(undef, "$aws_status &nbsp;|&nbsp; $mode", 2);

    # CF status
    my $cf = $cache->{'cf_status'};
    my $cf_status = "";
    if (!$config{'cf_api_token'}) {
        $cf_status = "<span style='color:grey'>&#8212;</span> Cloudflare: Not configured";
    } elsif ($cf->{'ok'}) {
        $cf_status = "<span style='color:green'>&#10003;</span> Cloudflare: Valid ($cf->{'zones'} zones)";
    } else {
        $cf_status = "<span style='color:red'>&#10007;</span> Cloudflare: $cf->{'error'}";
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

my $icon_yes = "<span style='color:green'>&#10003;</span>";
my $icon_no = "<span style='color:grey'>&#8212;</span>";
my $icon_pending = "<span style='color:orange'>&#9203;</span>";
my $icon_warn = "<span style='color:orange'>&#63;</span>";

my $domain_data = $cache->{'domains'} || {};
foreach my $dom (sort keys %$domain_data) {
    my $d = $domain_data->{$dom};
    my $state = get_domain_state($dom);
    my $status;
    my @buttons;
    my $status_msg = "";

    if (!$state || !$state->{'enabled'}) {
        # DISABLED state
        my $ses_col = $icon_no;
        my $dkim_col = $d->{'dkim'} ? $icon_yes : $icon_no;
        my $spf_col = $d->{'spf'} ? $icon_yes : $icon_no;
        my $dmarc_col = $d->{'dmarc'} ? $icon_yes : $icon_no;
        my $cf_col = $d->{'on_cf'} ? $icon_yes : $icon_no;
        my $provider = $d->{'provider'} || 'Unknown';

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
        my $ses_col = $d->{'ses_exists'} ? $icon_yes : $icon_no;
        my $dkim_s = $d->{'dkim_status'} || '';
        my $dkim_col = $dkim_s eq 'SUCCESS' ? $icon_yes : ($dkim_s eq 'PENDING' ? $icon_pending : $icon_no);
        my $spf_col = $d->{'spf'} ? $icon_yes : $icon_warn;
        my $dmarc_col = $d->{'dmarc'} ? $icon_yes : $icon_warn;
        my $cf_col = $d->{'on_cf'} ? $icon_yes : "<span style='color:grey'>&#10007;</span>";
        my $provider = $d->{'provider'} || 'Unknown';

        $status = "<span style='color:orange'>$text{'status_paused'}</span>";
        $status_msg = "<br><small>$text{'paused_msg'}</small>";
        @buttons = (
            "<a href='pause_domain.cgi?dom=$dom&action=resume'>$text{'btn_resume'}</a>",
            "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>"
        );
        print &ui_columns_row([
            "<b>$dom</b>$status_msg",
            $ses_col, $dkim_col, $spf_col, $dmarc_col, $cf_col,
            $provider,
            $status,
            join(" &nbsp; ", @buttons)
        ]);
    } else {
        # ENABLED state
        my $ses_col = $d->{'ses_exists'} ? $icon_yes : $icon_no;
        my $dkim_s = $d->{'dkim_status'} || '';
        my $dkim_col;
        if ($dkim_s eq 'SUCCESS') {
            $dkim_col = $icon_yes;
        } elsif ($dkim_s eq 'PENDING') {
            $dkim_col = $icon_pending;
        } else {
            $dkim_col = "<span style='color:red'>&#10007;</span>";
        }
        my $spf_col = $d->{'spf'} ? $icon_yes : $icon_warn;
        my $dmarc_col = $d->{'dmarc'} ? $icon_yes : $icon_warn;
        my $cf_col = $d->{'on_cf'} ? $icon_yes : "<span style='color:grey'>&#10007;</span>";
        my $provider = $d->{'provider'} || 'Unknown';

        my $overall_status = $d->{'overall'} || 'UNKNOWN';
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
                "<a href='index.cgi?refresh=1'>$text{'btn_recheck'}</a>"
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
            my $dns_prov = $d->{'dns_provider'} || '';
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
            my $issues_str = join(", ", @{$d->{'issues'} || []});
            $status_msg = "<br><small>$issues_str</small>" if $issues_str;
            @buttons = (
                "<a href='fix_domain.cgi?dom=$dom'>$text{'btn_fix'}</a>",
                "<a href='pause_domain.cgi?dom=$dom&action=pause'>$text{'btn_pause'}</a>",
                "<a href='disable_domain.cgi?dom=$dom'>$text{'btn_disable'}</a>"
            );
        }

        print &ui_columns_row([
            "<b>$dom</b>$status_msg",
            $ses_col, $dkim_col, $spf_col, $dmarc_col, $cf_col,
            $provider,
            $overall,
            join(" &nbsp; ", @buttons)
        ]);
    }
}

print &ui_columns_end();

# Recent mail log (always live — cheap to read)
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

#######################################################################
# Data fetching — builds the cache hash
#######################################################################

sub fetch_dashboard_data {
    my %data;

    # SES account health
    my ($health, $health_err) = ses_get_account_health();
    if ($health && !$health_err) {
        $data{health} = $health;
    } else {
        $data{health} = { error => $health_err || 'Failed to connect' };
    }

    # Cloudflare status
    if ($config{'cf_api_token'}) {
        my ($cf_ok, $cf_err, $cf_zones) = cf_test_credentials();
        if ($cf_ok && !$cf_err) {
            $data{cf_status} = { ok => 1, zones => $cf_zones };
        } else {
            $data{cf_status} = { ok => 0, error => $cf_err };
        }
    } else {
        $data{cf_status} = { ok => 0, error => 'Not configured' };
    }

    # Get all domains
    my @domains = get_virtualmin_domains();

    # Pre-fetch Cloudflare zones and records
    my %cf_zone_map;
    my %cf_records;
    if ($config{'cf_api_token'}) {
        my ($zdata, $zerr) = cf_api_call('GET', 'zones?per_page=50');
        if ($zdata && $zdata->{result}) {
            # Match domains to zones
            foreach my $dom (@domains) {
                foreach my $zone (@{$zdata->{result}}) {
                    if ($dom eq $zone->{name} || $dom =~ /\.\Q$zone->{name}\E$/) {
                        $cf_zone_map{$dom} = $zone->{id};
                        last;
                    }
                }
            }

            # Fetch records per zone (one call per zone, not per domain)
            my %fetched_zones;
            foreach my $dom (keys %cf_zone_map) {
                my $zid = $cf_zone_map{$dom};
                unless ($fetched_zones{$zid}) {
                    my ($rdata, $rerr) = cf_api_call('GET', "zones/$zid/dns_records?per_page=500");
                    $fetched_zones{$zid} = $rdata->{result} || [] if !$rerr;
                    $fetched_zones{$zid} ||= [];
                }
                my @all = @{$fetched_zones{$zid}};
                $cf_records{$dom} = {
                    spf => [grep { $_->{type} eq 'TXT' && $_->{name} eq $dom && $_->{content} =~ /v=spf1/i } @all],
                    dmarc => [grep { $_->{type} eq 'TXT' && $_->{name} eq "_dmarc.$dom" } @all],
                    dkim => [grep { $_->{type} eq 'CNAME' && $_->{name} =~ /\._domainkey\.\Q$dom\E$/i } @all],
                    dkim_txt => [grep { $_->{type} eq 'TXT' && $_->{name} =~ /\._domainkey\.\Q$dom\E$/i } @all],
                };
            }
        }
    }

    # Build per-domain data
    my %dom_data;
    foreach my $dom (@domains) {
        my $state = get_domain_state($dom);

        if (!$state || !$state->{'enabled'}) {
            # DISABLED — check DNS only
            my %d = (provider => detect_mail_provider($dom), on_cf => 0, dkim => 0, spf => 0, dmarc => 0);

            if ($cf_zone_map{$dom} && $cf_records{$dom}) {
                $d{on_cf} = 1;
                my $r = $cf_records{$dom};
                $d{dkim} = (@{$r->{dkim}} || @{$r->{dkim_txt}}) ? 1 : 0;
                $d{spf} = @{$r->{spf}} ? 1 : 0;
                $d{dmarc} = @{$r->{dmarc}} ? 1 : 0;
            } else {
                # DNS resolver fallback
                eval {
                    my $res = Net::DNS::Resolver->new(udp_timeout => 2, tcp_timeout => 2);
                    for my $sel ('202410', 'default', 'selector1', 'google', 'dkim') {
                        my $r = $res->query("${sel}._domainkey.$dom", 'TXT')
                              || $res->query("${sel}._domainkey.$dom", 'CNAME');
                        if ($r) { $d{dkim} = 1; last; }
                    }
                    my $spf_reply = $res->query($dom, 'TXT');
                    if ($spf_reply) {
                        foreach my $rr ($spf_reply->answer) {
                            if ($rr->type eq 'TXT' && $rr->txtdata =~ /v=spf1/i) {
                                $d{spf} = 1; last;
                            }
                        }
                    }
                    my $dmarc_reply = $res->query("_dmarc.$dom", 'TXT');
                    if ($dmarc_reply) {
                        foreach my $rr ($dmarc_reply->answer) {
                            if ($rr->type eq 'TXT' && $rr->txtdata =~ /v=DMARC1/i) {
                                $d{dmarc} = 1; last;
                            }
                        }
                    }
                };
            }
            $dom_data{$dom} = \%d;

        } else {
            # ENABLED or PAUSED — get full SES status
            my $s = get_domain_ses_status($dom);
            my %d = (
                provider    => $s->{'mail_provider'} || detect_mail_provider($dom),
                on_cf       => $s->{'on_cloudflare'} ? 1 : 0,
                ses_exists  => $s->{'ses_exists'} ? 1 : 0,
                dkim_status => $s->{'dkim_status'} || '',
                dkim        => (($s->{'dkim_status'} || '') eq 'SUCCESS') ? 1 : 0,
                spf         => $s->{'spf_ok'} ? 1 : 0,
                dmarc       => $s->{'dmarc_ok'} ? 1 : 0,
                overall     => $s->{'overall'} || 'UNKNOWN',
                issues      => $s->{'issues'} || [],
                dns_provider => '',
            );
            if ($s->{'overall'} eq 'MANUAL_DNS') {
                $d{dns_provider} = get_dns_provider($dom);
            }
            $dom_data{$dom} = \%d;
        }
    }

    $data{domains} = \%dom_data;
    return \%data;
}
