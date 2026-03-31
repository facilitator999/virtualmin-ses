#!/usr/bin/perl
# Disable SES for a domain

require './virtualmin-ses-lib.pl';
&ReadParse();

my $dom = $in{'dom'} || &error("No domain specified");

ui_print_header(undef, &text('disable_title', $dom), "");

# Confirmation step
if (!$in{'confirm'}) {
    # Show diff if backup exists
    my $backup = get_dns_backup($dom);
    if ($backup) {
        print "<p><b>$text{'disable_diff'}:</b></p>";
        my $diff = diff_dns_backup($dom);
        if ($diff && @$diff) {
            print "<pre style='background:#f5f5f5;padding:10px;border-radius:4px'>";
            foreach my $d (@$diff) {
                print &html_escape($d) . "\n";
            }
            print "</pre>";
        } else {
            print "<p><i>No changes since backup</i></p>";
        }
    }

    print "<p style='color:#856404;background:#fff3cd;padding:10px;border-radius:4px'>";
    print "$text{'disable_confirm'}</p>";

    print &ui_form_start("disable_domain.cgi", "post");
    print &ui_hidden("dom", $dom);
    print &ui_hidden("confirm", 1);
    print &ui_form_end([[$text{'btn_disable'}, $text{'btn_disable'}]]);
    ui_print_footer("index.cgi", $text{'index_title'});
    exit;
}

# Step 1: Remove from transport map
print "<p>$text{'disable_transport'}";
my $t_result = remove_domain_from_transport($dom);
print($t_result->{'ok'} ? " <span style='color:green'>&#10003;</span>" : " <span style='color:orange'>&#9888;</span>");
print "</p>";

# Step 2: Remove SES identity
print "<p>$text{'disable_identity'}";
my $ses_result = ses_delete_identity($dom);
print($ses_result->{'ok'} ? " <span style='color:green'>&#10003;</span>" : " <span style='color:orange'>&#9888;</span>");
print "</p>";

# Step 3: Restore DNS from backup
my $state = get_domain_state($dom);
my $cf_zone = $state->{'cf_zone'};
if ($cf_zone) {
    print "<p>$text{'disable_dns'}";
    my $restore_result = restore_domain_dns($dom, $cf_zone);
    print($restore_result->{'ok'} ? " <span style='color:green'>&#10003;</span>" : " <span style='color:orange'>&#9888;</span> $restore_result->{'error'}");
    print "</p>";
}

# Step 4: Restore OpenDKIM
restore_opendkim_for_domain($dom);

# Step 5: Delete state
delete_domain_state($dom);

print "<p style='color:green'><b>" . &text('disable_done', $dom) . "</b></p>";
ui_print_footer("index.cgi", $text{'index_title'});
