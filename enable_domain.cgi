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

clear_dashboard_cache();

ensure_dirs();

my $region = $config{'aws_region'} || 'eu-west-1';
my $smtp_endpoint = get_ses_smtp_endpoint($region);
my @errors;

# Step 1: Backup DNS
print "<p>$text{'enable_backup'}";
my ($cf_zone, $cf_zone_name);
if ($config{'cf_api_token'}) {
    ($cf_zone, $cf_zone_name) = cf_get_zone_for_domain($dom);
}
if ($cf_zone) {
    my $backup = backup_domain_dns($dom, $cf_zone);
    if ($backup) {
        print " <span style='color:green'>&#10003;</span></p>";
    } else {
        print " <span style='color:orange'>&#9888;</span> backup failed</p>";
    }
} else {
    print " <span style='color:grey'>(non-Cloudflare — skipped)</span></p>";
}

# Step 2: Create SES identity
print "<p>$text{'enable_create'}";
my ($identity_data, $identity_err);
if (ses_identity_exists($dom)) {
    print " $text{'enable_err_exists'}";
    ($identity_data, $identity_err) = ses_get_identity($dom);
} else {
    ($identity_data, $identity_err) = ses_create_identity($dom);
}

if (!$identity_err && $identity_data) {
    print " <span style='color:green'>&#10003;</span></p>";
} else {
    print " <span style='color:red'>&#10007;</span></p>";
    print "<p style='color:red'>" . &text('enable_err_create', $identity_err) . "</p>";
    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

# Step 3: Get DKIM tokens
print "<p>$text{'enable_dkim'}";
my @dkim_tokens;
if ($identity_data->{'DkimAttributes'} && $identity_data->{'DkimAttributes'}{'Tokens'}) {
    @dkim_tokens = @{$identity_data->{'DkimAttributes'}{'Tokens'}};
}
unless (@dkim_tokens) {
    my ($tokens, $terr, $tstatus) = ses_get_dkim_tokens($dom);
    @dkim_tokens = @{$tokens || []};
}
if (@dkim_tokens) {
    print " <span style='color:green'>&#10003;</span> (" . scalar(@dkim_tokens) . " tokens)</p>";
} else {
    print " <span style='color:orange'>&#9888;</span> No DKIM tokens returned</p>";
}

# Step 4: Push DNS records (if Cloudflare)
if ($cf_zone) {
    print "<p>$text{'enable_dns'}";
    my $dns_ok = 1;

    # DKIM CNAMEs
    foreach my $token (@dkim_tokens) {
        my $name = "${token}._domainkey.${dom}";
        my $value = "${token}.dkim.amazonses.com";
        my ($status, $id_or_err) = cf_ensure_dns_record($cf_zone, 'CNAME', $name, $value);
        if ($status eq 'error') {
            $dns_ok = 0;
            push @errors, "DKIM CNAME: $id_or_err";
        }
    }

    # SPF merge
    my ($spf_status, $spf_id, @spf_warnings) = merge_spf_record($dom, $cf_zone);
    if ($spf_status eq 'error') {
        push @errors, "SPF: $spf_id";
    }
    foreach my $w (@spf_warnings) {
        print "<br><small style='color:orange'>&#9888; $w</small>";
    }

    # DMARC (only if none exists)
    my $dmarc_rec = build_dmarc_record($dom);
    my @existing_dmarc = cf_list_dns_records($cf_zone, 'TXT', "_dmarc.$dom");
    if (!@existing_dmarc) {
        my ($dmarc_status, $dmarc_id) = cf_ensure_dns_record($cf_zone, 'TXT', "_dmarc.$dom", $dmarc_rec);
        if ($dmarc_status eq 'error') {
            push @errors, "DMARC: $dmarc_id";
        }
    }

    if ($dns_ok && !@errors) {
        print " <span style='color:green'>&#10003;</span></p>";
    } else {
        print " <span style='color:red'>&#10007;</span></p>";
        foreach my $err (@errors) {
            print "<p style='color:red'>" . &text('enable_err_dns', $err) . "</p>";
        }
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
if (!$pf_status->{'routing_configured'}) {
    configure_postfix_ses($region);
}
add_domain_to_transport($dom);
print " <span style='color:green'>&#10003;</span></p>";

# Step 6: Disable OpenDKIM for this domain
print "<p>$text{'enable_opendkim'}";
disable_opendkim_for_domain($dom);
print " <span style='color:green'>&#10003;</span></p>";

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
