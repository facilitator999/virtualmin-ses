#!/usr/bin/perl
# View recent mail log entries

require './virtualmin-ses-lib.pl';
&ReadParse();

ui_print_header(undef, $text{'log_title'}, "");

my $domain = $in{'domain'} || '';
my $count = $in{'count'} || 50;

# Domain filter
my @domains = get_virtualmin_domains();
print &ui_form_start("view_log.cgi", "get");
print &ui_table_start(undef, undef, 2);
print &ui_table_row($text{'log_domain'},
    &ui_select("domain", $domain,
        [['', $text{'log_all'}], map { [$_, $_] } sort @domains]));
print &ui_table_row($text{'log_recent'},
    &ui_select("count", $count,
        [[20, "20"], [50, "50"], [100, "100"], [200, "200"]]));
print &ui_table_end();
print &ui_form_end([["filter", "Filter"]]);

# Get log entries
my @log = get_recent_mail_log($domain || undef, $count);

if (@log) {
    print "<pre style='background:#f5f5f5;padding:10px;border-radius:4px;font-size:12px;max-height:600px;overflow-y:auto'>";
    foreach my $entry (@log) {
        print &html_escape($entry) . "\n";
    }
    print "</pre>";
} else {
    print "<p><i>No log entries found" . ($domain ? " for $domain" : "") . "</i></p>";
}

ui_print_footer("index.cgi", $text{'index_title'});
