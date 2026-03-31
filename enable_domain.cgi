#!/usr/bin/perl
# Enable SES for a domain

require './virtualmin-ses-lib.pl';
&ReadParse();

my $dom = $in{'dom'} || &error("No domain specified");

ui_print_header(undef, &text('enable_title', $dom), "");

# Pre-checks
if (!$config{'aws_access_key'} || !$config{'aws_secret_key'}) {
    print "<p style='color:red'>$text{'enable_err_creds'}</p>";
    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

ensure_dirs();

my $region = $config{'aws_region'} || 'eu-west-1';
my $smtp_endpoint = get_ses_smtp_endpoint($region);
my @errors;

# Step 1: Backup DNS
print "<p>$text{'enable_backup'}";
my $cf_zone = undef;
if ($config{'cf_api_token'}) {
    $cf_zone = cf_get_zone_for_domain($dom);
}
if ($cf_zone) {
    my $backup_result = backup_domain_dns($dom, $cf_zone);
    if ($backup_result->{'ok'}) {
        print " <span style='color:green'>&#10003;</span></p>";
    } else {
        print " <span style='color:orange'>&#9888;</span> $backup_result->{'error'}</p>";
    }
} else {
    print " <span style='color:grey'>(non-Cloudflare — skipped)</span></p>";
}

# Step 2: Create SES identity
print "<p>$text{'enable_create'}";
my $identity_result;
if (ses_identity_exists($dom)) {
    print " $text{'enable_err_exists'}";
    $identity_result = ses_get_identity($dom);
} else {
    $identity_result = ses_create_identity($dom);
}

if ($identity_result->{'ok'}) {
    print " <span style='color:green'>&#10003;</span></p>";
} else {
    my $err = $identity_result->{'error'};
    print " <span style='color:red'>&#10007;</span></p>";
    print "<p style='color:red'>" . &text('enable_err_create', $err) . "</p>";
    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

# Step 3: Get DKIM tokens
print "<p>$text{'enable_dkim'}";
my @dkim_tokens = @{$identity_result->{'dkim_tokens'} || []};
if (@dkim_tokens) {
    print " <span style='color:green'>&#10003;</span> (" . scalar(@dkim_tokens) . " tokens)</p>";
} else {
    # Try fetching separately
    my $dkim_result = ses_get_dkim_tokens($dom);
    @dkim_tokens = @{$dkim_result->{'tokens'} || []};
    if (@dkim_tokens) {
        print " <span style='color:green'>&#10003;</span> (" . scalar(@dkim_tokens) . " tokens)</p>";
    } else {
        print " <span style='color:orange'>&#9888;</span> No DKIM tokens returned</p>";
    }
}

# Step 4: Push DNS records (if Cloudflare)
if ($cf_zone) {
    print "<p>$text{'enable_dns'}";
    my $dns_ok = 1;
    my @rollback;

    # DKIM CNAMEs
    foreach my $token (@dkim_tokens) {
        my $name = "${token}._domainkey.${dom}";
        my $value = "${token}.dkim.amazonses.com";
        my $result = cf_ensure_dns_record($cf_zone, 'CNAME', $name, $value);
        if ($result->{'ok'}) {
            push @rollback, $result->{'id'};
        } else {
            $dns_ok = 0;
            push @errors, "DKIM CNAME: $result->{'error'}";
        }
    }

    # SPF merge
    my $spf_result = merge_spf_record($dom, $cf_zone);
    if (!$spf_result->{'ok'}) {
        push @errors, "SPF: $spf_result->{'error'}" unless $spf_result->{'skipped'};
    }

    # DMARC (only if none exists)
    my $dmarc_rec = build_dmarc_record($dom);
    my @existing_dmarc = @{cf_list_dns_records($cf_zone, 'TXT', "_dmarc.$dom") || []};
    if (!@existing_dmarc) {
        my $dmarc_result = cf_ensure_dns_record($cf_zone, 'TXT', "_dmarc.$dom", $dmarc_rec);
        if (!$dmarc_result->{'ok'}) {
            push @errors, "DMARC: $dmarc_result->{'error'}";
        }
    }

    if ($dns_ok && !@errors) {
        print " <span style='color:green'>&#10003;</span></p>";
    } elsif (@errors) {
        print " <span style='color:red'>&#10007;</span></p>";
        foreach my $err (@errors) {
            print "<p style='color:red'>" . &text('enable_err_dns', $err) . "</p>";
        }
        # Don't exit — still set up transport so it can be fixed later
    }
} else {
    # Non-Cloudflare domain
    print "<p><b>DNS provider is not Cloudflare.</b> You need to add these records manually:</p>";
    print "<table border=1 cellpadding=5 style='border-collapse:collapse;margin:10px 0'>";
    print "<tr><th>Type</th><th>Name</th><th>Value</th></tr>";
    foreach my $token (@dkim_tokens) {
        print "<tr><td>CNAME</td><td>${token}._domainkey.${dom}</td><td>${token}.dkim.amazonses.com</td></tr>";
    }
    my $spf_val = build_spf_record($dom);
    print "<tr><td>TXT</td><td>$dom</td><td>$spf_val</td></tr>";
    my $dmarc_val = build_dmarc_record($dom);
    print "<tr><td>TXT</td><td>_dmarc.$dom</td><td>$dmarc_val</td></tr>";
    print "</table>";
}

# Step 5: Add to Postfix transport map
print "<p>$text{'enable_transport'}";
my $pf_status = get_postfix_ses_status();
if (!$pf_status->{'routing'}) {
    # One-time Postfix setup
    my $pf_result = configure_postfix_ses($region);
    if (!$pf_result->{'ok'}) {
        print " <span style='color:red'>&#10007;</span> Postfix setup failed: $pf_result->{'error'}</p>";
        push @errors, "Postfix: $pf_result->{'error'}";
    }
}
my $transport_result = add_domain_to_transport($dom);
if ($transport_result->{'ok'}) {
    print " <span style='color:green'>&#10003;</span></p>";
} else {
    print " <span style='color:red'>&#10007;</span> $transport_result->{'error'}</p>";
}

# Step 6: Disable OpenDKIM for this domain
print "<p>$text{'enable_opendkim'}";
my $dkim_result = disable_opendkim_for_domain($dom);
if ($dkim_result->{'ok'}) {
    print " <span style='color:green'>&#10003;</span></p>";
} else {
    print " <span style='color:grey'>(skipped: $dkim_result->{'error'})</span></p>";
}

# Save state
save_domain_state($dom, {
    'enabled' => 1,
    'paused' => 0,
    'enabled_at' => time(),
    'dkim_tokens' => \@dkim_tokens,
    'cf_zone' => $cf_zone,
});

# Done
if (@errors) {
    print "<p style='color:orange'><b>SES enabled with warnings. Some DNS records may need manual attention.</b></p>";
} else {
    print "<p style='color:green'><b>" . &text('enable_done', $dom) . "</b></p>";
}

ui_print_footer("index.cgi", $text{'index_title'});
