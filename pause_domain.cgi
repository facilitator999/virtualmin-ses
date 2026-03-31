#!/usr/bin/perl
# Pause or Resume SES for a domain

require './virtualmin-ses-lib.pl';
&ReadParse();

my $dom = $in{'dom'} || &error("No domain specified");
my $action = $in{'action'} || 'pause';

clear_dashboard_cache();

if ($action eq 'resume') {
    # Resume: add back to transport map
    my $result = add_domain_to_transport($dom);
    my $state = get_domain_state($dom);
    $state->{'paused'} = 0;
    save_domain_state($dom, $state);

    ui_print_header(undef, &text('resume_done', $dom), "");
    print "<p style='color:green'><b>" . &text('resume_done', $dom) . "</b></p>";
} else {
    # Pause: remove from transport map but keep identity + DNS
    my $result = remove_domain_from_transport($dom);
    my $state = get_domain_state($dom);
    $state->{'paused'} = 1;
    save_domain_state($dom, $state);

    ui_print_header(undef, &text('pause_title', $dom), "");
    print "<p style='color:orange'><b>" . &text('pause_done', $dom) . "</b></p>";
}

ui_print_footer("index.cgi", $text{'index_title'});
