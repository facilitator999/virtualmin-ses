#!/usr/bin/perl
# Emergency disable all SES routing

require './virtualmin-ses-lib.pl';
&ReadParse();

ui_print_header(undef, $text{'emergency_title'}, "");

if (!$in{'confirm'}) {
    print "<p style='color:#721c24;background:#f8d7da;padding:15px;border-radius:4px;font-size:16px'>";
    print "<b>$text{'emergency_confirm'}</b></p>";

    # Show what will be affected
    my @enabled = list_enabled_domains();
    if (@enabled) {
        print "<p>Domains currently routing through SES:</p><ul>";
        foreach my $dom (@enabled) {
            print "<li><b>$dom</b></li>";
        }
        print "</ul>";
    }

    print &ui_form_start("emergency.cgi", "post");
    print &ui_hidden("confirm", 1);
    print &ui_form_end([[$text{'index_emergency'}, $text{'index_emergency'}]]);
    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

clear_dashboard_cache();

# Do the emergency disable
print "<p>Removing all SES routing...</p>";
my $result = remove_all_from_transport();

# Update all domain states to paused
my @enabled = list_enabled_domains();
foreach my $dom (@enabled) {
    my $state = get_domain_state($dom);
    if ($state && $state->{'enabled'} && !$state->{'paused'}) {
        $state->{'paused'} = 1;
        save_domain_state($dom, $state);
    }
}

print "<p style='color:green'><b>$text{'emergency_done'}</b></p>";
ui_print_footer("index.cgi", $text{'index_title'});
