#!/usr/bin/perl
# Send test email via SES

require './virtualmin-ses-lib.pl';
&ReadParse();

ui_print_header(undef, $text{'test_title'}, "");

my $dom = $in{'dom'};

if ($in{'send'}) {
    # Send the test email
    my $from = $in{'from_domain'};
    my $to = $in{'to_address'};

    if (!$from || !$to) {
        &error("From domain and To address are required");
    }

    print "<p>Sending test email from $from to $to...</p>";
    my $result = send_test_email($from, $to);

    if ($result->{'success'}) {
        print "<p style='color:green'><b>$text{'test_success'}</b></p>";
    } else {
        print "<p style='color:red'><b>" . &text('test_fail', $result->{'output'} || 'Unknown error') . "</b></p>";
    }

    if ($result->{'log'} && ref($result->{'log'}) eq 'ARRAY' && @{$result->{'log'}}) {
        print "<pre style='background:#f5f5f5;padding:10px;border-radius:4px;font-size:12px'>";
        foreach my $entry (@{$result->{'log'}}) {
            print &html_escape($entry) . "\n";
        }
        print "</pre>";
    }
} else {
    # Show form
    my @domains = get_virtualmin_domains();
    my @enabled;
    foreach my $d (sort @domains) {
        my $state = get_domain_state($d);
        push @enabled, $d if ($state && $state->{'enabled'} && !$state->{'paused'});
    }

    if (!@enabled) {
        print "<p>No domains have SES enabled and active. Enable SES for a domain first.</p>";
        ui_print_footer("index.cgi", $text{'index_title'});
        exit;
    }

    print &ui_form_start("test_email.cgi", "post");
    print &ui_hidden("send", 1);

    print &ui_table_start(undef, "width=100%", 2);

    my $default_dom = $dom || $enabled[0];
    print &ui_table_row($text{'test_from'},
        &ui_select("from_domain", $default_dom, [map { [$_, $_] } @enabled]));

    print &ui_table_row($text{'test_to'},
        &ui_textbox("to_address", "", 40));

    print &ui_table_end();
    print &ui_form_end([[$text{'test_send'}, $text{'test_send'}]]);
}

ui_print_footer("index.cgi", $text{'index_title'});
