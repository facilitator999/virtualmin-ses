#!/usr/bin/perl
# Save settings for AWS SES Email Delivery plugin

require './virtualmin-ses-lib.pl';
&ReadParse();

# Handle Postfix reconfigure button
if ($in{'reconfig_postfix'}) {
    my $result = configure_postfix_ses($in{'aws_region'} || $config{'aws_region'} || 'eu-west-1');
    if ($result->{'ok'}) {
        &redirect("settings.cgi");
    } else {
        &error($result->{'error'});
    }
    return;
}

# Handle Postfix restore button
if ($in{'restore_postfix'}) {
    my $result = restore_postfix_backup();
    if ($result->{'ok'}) {
        &redirect("settings.cgi");
    } else {
        &error($result->{'error'});
    }
    return;
}

# Validate AWS credentials if provided
if ($in{'aws_access_key'} && $in{'aws_secret_key'}) {
    # Temporarily set config for testing
    $config{'aws_access_key'} = $in{'aws_access_key'};
    $config{'aws_secret_key'} = $in{'aws_secret_key'};
    $config{'aws_region'} = $in{'aws_region'};
    my $result = ses_test_credentials();
    if (!$result->{'ok'}) {
        &error($text{'settings_err_aws'} . ": " . $result->{'error'});
    }
}

# Validate Cloudflare token if provided
if ($in{'cf_api_token'}) {
    $config{'cf_api_token'} = $in{'cf_api_token'};
    my $result = cf_test_credentials();
    if (!$result->{'ok'}) {
        &error($text{'settings_err_cf'} . ": " . $result->{'error'});
    }
}

# Save config
$config{'aws_access_key'} = $in{'aws_access_key'};
$config{'aws_secret_key'} = $in{'aws_secret_key'};
$config{'aws_region'} = $in{'aws_region'};
$config{'cf_api_token'} = $in{'cf_api_token'};
$config{'spf_include'} = $in{'spf_include'} || 'amazonses.com';
$config{'dmarc_policy'} = $in{'dmarc_policy'} || 'none';
$config{'dmarc_rua'} = $in{'dmarc_rua'};
&save_module_config();

# If AWS credentials changed and Postfix is configured, update SASL
if ($in{'aws_access_key'} && $in{'aws_secret_key'}) {
    my $pf_status = get_postfix_ses_status();
    if ($pf_status->{'routing'}) {
        # Update SASL credentials
        my $smtp_pass = ses_derive_smtp_credentials($in{'aws_secret_key'}, $in{'aws_region'});
        my $smtp_endpoint = get_ses_smtp_endpoint($in{'aws_region'});
        my $sasl_file = "/etc/postfix/sasl_passwd";
        open(my $fh, ">", $sasl_file) or &error("Cannot write $sasl_file: $!");
        print $fh "[$smtp_endpoint]:587 $in{'aws_access_key'}:$smtp_pass\n";
        close($fh);
        chmod(0600, $sasl_file);
        system("postmap $sasl_file 2>/dev/null");
    }
}

&redirect("settings.cgi");
