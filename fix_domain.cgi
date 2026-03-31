#!/usr/bin/perl
# Fix domain issues or show required DNS records

require './virtualmin-ses-lib.pl';
&ReadParse();

my $dom = $in{'dom'} || &error("No domain specified");
my $action = $in{'action'} || 'fix';

ui_print_header(undef, &text('fix_title', $dom), "");

my $state = get_domain_state($dom);

if ($action eq 'showrecords') {
    # Show required DNS records for manual DNS domains
    my @dkim_tokens = @{$state->{'dkim_tokens'} || []};
    if (!@dkim_tokens) {
        my $dkim_result = ses_get_dkim_tokens($dom);
        @dkim_tokens = @{$dkim_result->{'tokens'} || []};
    }

    print "<p>Add these DNS records at your DNS provider:</p>";
    print "<table border=1 cellpadding=5 style='border-collapse:collapse;margin:10px 0'>";
    print "<tr><th>Type</th><th>Name</th><th>Value</th><th>Proxy</th></tr>";
    foreach my $token (@dkim_tokens) {
        print "<tr><td>CNAME</td><td>${token}._domainkey.${dom}</td><td>${token}.dkim.amazonses.com</td><td>OFF</td></tr>";
    }
    my $spf_val = build_spf_record($dom);
    print "<tr><td>TXT</td><td>$dom</td><td>$spf_val</td><td>N/A</td></tr>";
    my $dmarc_val = build_dmarc_record($dom);
    print "<tr><td>TXT</td><td>_dmarc.$dom</td><td>$dmarc_val</td><td>N/A</td></tr>";
    print "</table>";

    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

if ($action eq 'checkdns') {
    # Check DNS propagation for manually managed domains
    print "<p>Checking DNS for $dom...</p>";

    my $ses_status = get_domain_ses_status($dom);
    print "<table border=0 cellpadding=3>";
    print "<tr><td>SES Identity:</td><td>" . ($ses_status->{'ses'} ? "<span style='color:green'>&#10003;</span>" : "<span style='color:red'>&#10007;</span>") . "</td></tr>";
    print "<tr><td>DKIM:</td><td>" . ($ses_status->{'dkim'} eq 'SUCCESS' ? "<span style='color:green'>&#10003; Verified</span>" : ($ses_status->{'dkim'} eq 'PENDING' ? "<span style='color:orange'>&#9203; Pending</span>" : "<span style='color:red'>&#10007; $ses_status->{'dkim'}</span>")) . "</td></tr>";
    print "<tr><td>SPF:</td><td>" . ($ses_status->{'spf'} ? "<span style='color:green'>&#10003;</span>" : "<span style='color:red'>&#10007;</span>") . "</td></tr>";
    print "<tr><td>DMARC:</td><td>" . ($ses_status->{'dmarc'} ? "<span style='color:green'>&#10003;</span>" : "<span style='color:red'>&#10007;</span>") . "</td></tr>";
    print "</table>";

    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

# Default: auto-fix
my $ses_status = get_domain_ses_status($dom);
my @fixes;

# Check DKIM
if ($ses_status->{'dkim'} eq 'PENDING') {
    my $elapsed = time() - ($state->{'enabled_at'} || 0);
    my $hours = int($elapsed / 3600);
    my $time_str = $hours > 24 ? int($hours/24) . "d" : "${hours}h";
    print "<p>" . &text('fix_dkim_pending', $time_str) . "</p>";
} elsif ($ses_status->{'dkim'} ne 'SUCCESS') {
    print "<p>$text{'fix_dkim_failed'}";
    if ($state->{'cf_zone'} && $state->{'dkim_tokens'}) {
        foreach my $token (@{$state->{'dkim_tokens'}}) {
            my $name = "${token}._domainkey.${dom}";
            my $value = "${token}.dkim.amazonses.com";
            cf_ensure_dns_record($state->{'cf_zone'}, 'CNAME', $name, $value);
        }
        print " <span style='color:green'>&#10003;</span>";
        push @fixes, 'dkim';
    }
    print "</p>";
}

# Check SPF
if (!$ses_status->{'spf'}) {
    print "<p>" . &text('fix_spf_wrong', "include:" . ($config{'spf_include'} || 'amazonses.com'));
    if ($state->{'cf_zone'}) {
        my $result = merge_spf_record($dom, $state->{'cf_zone'});
        print $result->{'ok'} ? " <span style='color:green'>&#10003;</span>" : " <span style='color:red'>&#10007;</span> $result->{'error'}";
        push @fixes, 'spf' if $result->{'ok'};
    }
    print "</p>";
}

# Check DMARC
if (!$ses_status->{'dmarc'}) {
    print "<p>$text{'fix_dmarc_missing'}";
    if ($state->{'cf_zone'}) {
        my $dmarc_rec = build_dmarc_record($dom);
        my $result = cf_ensure_dns_record($state->{'cf_zone'}, 'TXT', "_dmarc.$dom", $dmarc_rec);
        print $result->{'ok'} ? " <span style='color:green'>&#10003;</span>" : " <span style='color:red'>&#10007;</span> $result->{'error'}";
        push @fixes, 'dmarc' if $result->{'ok'};
    }
    print "</p>";
}

# Check SES identity
if (!$ses_status->{'ses'}) {
    print "<p>$text{'fix_ses_missing'}";
    my $result = ses_create_identity($dom);
    print $result->{'ok'} ? " <span style='color:green'>&#10003;</span>" : " <span style='color:red'>&#10007;</span> $result->{'error'}";
    push @fixes, 'ses' if $result->{'ok'};
    print "</p>";
}

if (@fixes) {
    print "<p style='color:green'><b>" . &text('fix_done', $dom) . "</b></p>";
} elsif ($ses_status->{'dkim'} ne 'PENDING') {
    print "<p>No issues found for $dom.</p>";
}

ui_print_footer("index.cgi", $text{'index_title'});
