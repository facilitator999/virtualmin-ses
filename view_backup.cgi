#!/usr/bin/perl
# View DNS backup for a domain

require './virtualmin-ses-lib.pl';
&ReadParse();

my $dom = $in{'dom'} || &error("No domain specified");

ui_print_header(undef, &text('backup_title', $dom), "");

my $backup = get_dns_backup($dom);
if (!$backup) {
    print "<p>$text{'backup_nobackup'}</p>";
    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

# Backup timestamp
if ($backup->{'timestamp'}) {
    my $ts = localtime($backup->{'timestamp'});
    print "<p>" . &text('backup_taken', $ts) . "</p>";
}

# Show original records from backup
print &ui_table_start($text{'backup_original'}, "width=100%", 3);
print &ui_columns_start(["Type", "Name", "Value"]);
if ($backup->{'records'}) {
    foreach my $rec (@{$backup->{'records'}}) {
        print &ui_columns_row([$rec->{'type'}, $rec->{'name'}, $rec->{'content'}]);
    }
}
print &ui_columns_end();
print &ui_table_end();

# Show diff
my $diff = diff_dns_backup($dom);
if ($diff && @$diff) {
    print &ui_table_start($text{'backup_diff'}, "width=100%", 1);
    print "<pre style='margin:5px;font-size:12px'>";
    foreach my $d (@$diff) {
        my $color = '';
        $color = 'color:green' if $d =~ /^\+/;
        $color = 'color:red' if $d =~ /^-/;
        print "<span style='$color'>" . &html_escape($d) . "</span>\n";
    }
    print "</pre>";
    print &ui_table_end();
}

ui_print_footer("index.cgi", $text{'index_title'});
