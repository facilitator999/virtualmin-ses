
# virtualmin-ses-lib.pl
# Core library for AWS SES Email Delivery Virtualmin plugin
# All AWS SES, Cloudflare, DNS, Postfix, and status functions

BEGIN { push(@INC, ".."); };
use WebminCore;
&init_config();

use LWP::UserAgent;
use HTTP::Request;
use JSON;
use Digest::SHA qw(hmac_sha256 hmac_sha256_hex sha256_hex sha256);
use MIME::Base64;
use URI::Escape;
use POSIX qw(strftime);
use Net::DNS;

our $BACKUP_DIR = "/etc/webmin/virtualmin-ses/backups";
our $TRANSPORT_MAP = "/etc/postfix/ses_relayhost_maps";
our $SASL_PASSWD = "/etc/postfix/sasl_passwd";
our $STATE_DIR = "/etc/webmin/virtualmin-ses/state";

# Ensure directories exist
sub ensure_dirs {
    foreach my $d ($BACKUP_DIR, $STATE_DIR) {
        if (!-d $d) {
            &make_dir($d, 0700, 1);
        }
    }
}

#######################################################################
# AWS Signature V4 Signing
#######################################################################

sub aws_sign_v4 {
    my ($method, $service, $region, $path, $query, $headers_ref, $payload,
        $access_key, $secret_key) = @_;

    my $host = "$service.$region.amazonaws.com";
    my $now = strftime("%Y%m%dT%H%M%SZ", gmtime());
    my $date = substr($now, 0, 8);

    # Canonical headers
    $headers_ref->{'host'} = $host;
    $headers_ref->{'x-amz-date'} = $now;

    my @signed_header_names = sort keys %$headers_ref;
    my $signed_headers = join(';', @signed_header_names);
    my $canonical_headers = '';
    foreach my $h (@signed_header_names) {
        $canonical_headers .= lc($h) . ':' . $headers_ref->{$h} . "\n";
    }

    my $payload_hash = sha256_hex($payload || '');

    # Canonical request
    my $canonical_request = join("\n",
        $method,
        $path || '/',
        $query || '',
        $canonical_headers,
        $signed_headers,
        $payload_hash
    );

    my $credential_scope = "$date/$region/$service/aws4_request";
    my $string_to_sign = join("\n",
        "AWS4-HMAC-SHA256",
        $now,
        $credential_scope,
        sha256_hex($canonical_request)
    );

    # Signing key
    my $k_date = hmac_sha256($date, "AWS4" . $secret_key);
    my $k_region = hmac_sha256($region, $k_date);
    my $k_service = hmac_sha256($service, $k_region);
    my $k_signing = hmac_sha256("aws4_request", $k_service);
    my $signature = hmac_sha256_hex($string_to_sign, $k_signing);

    my $auth = "AWS4-HMAC-SHA256 Credential=$access_key/$credential_scope, " .
               "SignedHeaders=$signed_headers, Signature=$signature";

    return ($auth, $now);
}

#######################################################################
# AWS SES API (pure Perl HTTP, SESv2 REST API)
#######################################################################

sub ses_endpoint {
    my $region = $config{'aws_region'} || 'eu-west-1';
    return "https://email.$region.amazonaws.com";
}

sub ses_api_call {
    my ($method, $path, $body, $query) = @_;

    my $access_key = $config{'aws_access_key'};
    my $secret_key = $config{'aws_secret_key'};
    my $region = $config{'aws_region'} || 'eu-west-1';

    return (undef, "AWS credentials not configured")
        unless $access_key && $secret_key;

    my %headers = ('content-type' => 'application/json');
    my $payload = $body ? encode_json($body) : '';

    my ($auth, $amz_date) = aws_sign_v4(
        $method, 'email', $region, "/v2$path", $query || '',
        \%headers, $payload, $access_key, $secret_key
    );

    my $url = ses_endpoint() . "/v2$path";
    $url .= "?$query" if $query;

    my $ua = LWP::UserAgent->new(timeout => 30);
    my $req = HTTP::Request->new($method, $url);
    $req->header('Authorization' => $auth);
    $req->header('X-Amz-Date' => $amz_date);
    $req->header('Content-Type' => 'application/json');
    $req->header('Host' => "email.$region.amazonaws.com");
    $req->content($payload) if $payload;

    my $resp = $ua->request($req);

    if ($resp->is_success) {
        my $data = eval { decode_json($resp->content) };
        return ($data || {}, undef);
    } else {
        my $err = $resp->content || $resp->status_line;
        my $parsed = eval { decode_json($err) };
        if ($parsed && $parsed->{message}) {
            return (undef, $parsed->{message});
        }
        return (undef, $resp->status_line . ": " . substr($err, 0, 200));
    }
}

sub ses_create_identity {
    my ($domain) = @_;
    my ($data, $err) = ses_api_call('POST', '/email/identities', {
        EmailIdentity => $domain
    });
    return ($data, $err);
}

sub ses_get_identity {
    my ($domain) = @_;
    my $encoded = uri_escape($domain);
    my ($data, $err) = ses_api_call('GET', "/email/identities/$encoded");
    return ($data, $err);
}

sub ses_delete_identity {
    my ($domain) = @_;
    my $encoded = uri_escape($domain);
    my ($data, $err) = ses_api_call('DELETE', "/email/identities/$encoded");
    return ($data, $err);
}

sub ses_list_identities {
    my ($data, $err) = ses_api_call('GET', '/email/identities', undef,
        'PageSize=100');
    return (undef, $err) if $err;
    my @domains;
    if ($data->{EmailIdentities}) {
        @domains = map { $_->{IdentityName} }
                   grep { ($_->{IdentityType} || '') eq 'DOMAIN' }
                   @{$data->{EmailIdentities}};
    }
    return (\@domains, undef);
}

sub ses_test_credentials {
    my ($data, $err) = ses_api_call('GET', '/account');
    return (undef, $err) if $err;
    return ($data, undef);
}

sub ses_get_account_health {
    my ($data, $err) = ses_test_credentials();
    return (undef, $err) if $err;

    my %health;
    $health{sandbox} = ($data->{ProductionAccessEnabled}) ? 0 : 1;
    $health{sending_enabled} = $data->{SendingEnabled} ? 1 : 0;

    if ($data->{SendQuota}) {
        $health{max_24h} = $data->{SendQuota}{Max24HourSend} || 0;
        $health{sent_24h} = $data->{SendQuota}{SentLast24Hours} || 0;
        $health{max_per_sec} = $data->{SendQuota}{MaxSendRate} || 0;
    }

    # Reputation metrics
    if ($data->{ReputationOptions}) {
        $health{reputation_tracking} = $data->{ReputationOptions}{ReputationMetricsEnabled} ? 1 : 0;
    }

    return (\%health, undef);
}

sub ses_get_dkim_tokens {
    my ($domain) = @_;
    my ($data, $err) = ses_get_identity($domain);
    return ([], $err) if $err;

    my @tokens;
    if ($data->{DkimAttributes} && $data->{DkimAttributes}{Tokens}) {
        @tokens = @{$data->{DkimAttributes}{Tokens}};
    }

    my $status = 'UNKNOWN';
    if ($data->{DkimAttributes}) {
        $status = $data->{DkimAttributes}{Status} || 'UNKNOWN';
    }

    return (\@tokens, undef, $status);
}

sub ses_identity_exists {
    my ($domain) = @_;
    my ($data, $err) = ses_get_identity($domain);
    return 0 if $err;
    return defined($data->{IdentityType}) ? 1 : 0;
}

sub ses_derive_smtp_credentials {
    my ($secret_key, $region) = @_;
    $region ||= $config{'aws_region'} || 'eu-west-1';

    # AWS documented algorithm for deriving SMTP password from IAM secret key
    my $date = "11111111";
    my $service = "ses";
    my $terminal = "aws4_request";
    my $message = "SendRawEmail";
    my $version = chr(0x04);

    my $k_date = hmac_sha256($date, "AWS4" . $secret_key);
    my $k_region = hmac_sha256($region, $k_date);
    my $k_service = hmac_sha256($service, $k_region);
    my $k_terminal = hmac_sha256($terminal, $k_service);
    my $k_message = hmac_sha256($message, $k_terminal);
    my $signature = $version . $k_message;

    return encode_base64($signature, '');
}

sub ses_get_suppression_list {
    my ($data, $err) = ses_api_call('GET', '/suppression/addresses',
        undef, 'PageSize=100');
    return ([], $err) if $err;
    my @addresses;
    if ($data->{SuppressedDestinationSummaries}) {
        @addresses = map {
            { email => $_->{EmailAddress}, reason => $_->{Reason},
              date => $_->{LastUpdateTime} }
        } @{$data->{SuppressedDestinationSummaries}};
    }
    return (\@addresses, undef);
}

sub ses_delete_suppressed {
    my ($email) = @_;
    my $encoded = uri_escape($email);
    return ses_api_call('DELETE', "/suppression/addresses/$encoded");
}

#######################################################################
# Cloudflare API
#######################################################################

sub cf_api_call {
    my ($method, $path, $body) = @_;

    my $token = $config{'cf_api_token'};
    return (undef, "Cloudflare API token not configured") unless $token;

    my $url = "https://api.cloudflare.com/client/v4/$path";
    my $ua = LWP::UserAgent->new(timeout => 30);
    my $req = HTTP::Request->new($method, $url);
    $req->header('Authorization' => "Bearer $token");
    $req->header('Content-Type' => 'application/json');
    $req->content(encode_json($body)) if $body;

    my $retries = 3;
    my $resp;
    for my $try (1..$retries) {
        $resp = $ua->request($req);
        last if $resp->code != 429;
        sleep(2 ** $try); # exponential backoff
    }

    my $data = eval { decode_json($resp->content) };
    if ($data && $data->{success}) {
        return ($data, undef);
    } elsif ($data && $data->{errors}) {
        my $msg = join(', ', map { $_->{message} || '' } @{$data->{errors}});
        return (undef, $msg || 'Unknown Cloudflare error');
    } else {
        return (undef, $resp->status_line);
    }
}

sub cf_test_credentials {
    my ($data, $err) = cf_api_call('GET', 'user/tokens/verify');
    return (0, $err) if $err;
    # Count zones
    my ($zdata, $zerr) = cf_api_call('GET', 'zones?per_page=1');
    my $zone_count = 0;
    $zone_count = $zdata->{result_info}{total_count} if $zdata && $zdata->{result_info};
    return (1, undef, $zone_count);
}

sub cf_get_zone_for_domain {
    my ($domain) = @_;

    # Walk up domain hierarchy to find the Cloudflare zone
    my @parts = split(/\./, $domain);
    for (my $i = 0; $i < scalar(@parts) - 1; $i++) {
        my $try = join('.', @parts[$i..$#parts]);
        # Skip public suffixes (2-part TLDs like co.uk, org.uk)
        next if $try =~ /^(co|org|net|ac|gov|me)\.[a-z]{2,3}$/i;
        next if length($try) < 4;

        my ($data, $err) = cf_api_call('GET', "zones?name=$try");
        next if $err;
        if ($data->{result} && @{$data->{result}}) {
            my $zone = $data->{result}[0];
            return ($zone->{id}, $zone->{name});
        }
    }
    return (undef, undef);
}

sub cf_list_dns_records {
    my ($zone_id, $type, $name) = @_;
    my $path = "zones/$zone_id/dns_records?per_page=100";
    $path .= "&type=$type" if $type;
    $path .= "&name=" . uri_escape($name) if $name;

    my ($data, $err) = cf_api_call('GET', $path);
    return () if $err;
    return @{$data->{result} || []};
}

sub cf_create_dns_record {
    my ($zone_id, $type, $name, $content, $proxied, $ttl) = @_;
    $proxied = 0 unless defined $proxied;
    $ttl = 1 unless $ttl; # 1 = auto

    my ($data, $err) = cf_api_call('POST', "zones/$zone_id/dns_records", {
        type => $type,
        name => $name,
        content => $content,
        proxied => $proxied ? JSON::true : JSON::false,
        ttl => $ttl + 0,
    });
    return ($data, $err);
}

sub cf_update_dns_record {
    my ($zone_id, $record_id, $type, $name, $content, $proxied, $ttl) = @_;
    $proxied = 0 unless defined $proxied;
    $ttl = 1 unless $ttl;

    my ($data, $err) = cf_api_call('PUT',
        "zones/$zone_id/dns_records/$record_id", {
        type => $type,
        name => $name,
        content => $content,
        proxied => $proxied ? JSON::true : JSON::false,
        ttl => $ttl + 0,
    });
    return ($data, $err);
}

sub cf_delete_dns_record {
    my ($zone_id, $record_id) = @_;
    return cf_api_call('DELETE', "zones/$zone_id/dns_records/$record_id");
}

sub cf_ensure_dns_record {
    my ($zone_id, $type, $name, $content, $proxied) = @_;
    $proxied = 0 unless defined $proxied;

    my @existing = cf_list_dns_records($zone_id, $type, $name);

    # Find matching record
    foreach my $rec (@existing) {
        if (lc($rec->{name}) eq lc($name) && $rec->{type} eq $type) {
            if ($rec->{content} eq $content) {
                return ('unchanged', $rec->{id});
            }
            # Update existing record
            my ($data, $err) = cf_update_dns_record(
                $zone_id, $rec->{id}, $type, $name, $content, $proxied);
            return $err ? ('error', $err) : ('updated', $rec->{id});
        }
    }

    # Create new record
    my ($data, $err) = cf_create_dns_record(
        $zone_id, $type, $name, $content, $proxied);
    if ($err) {
        return ('error', $err);
    }
    return ('created', $data->{result}{id});
}

#######################################################################
# DNS Record Builders
#######################################################################

sub get_server_ip {
    # Try to detect server's public IP
    my $ip;
    # Check Virtualmin's configured IP
    eval {
        &foreign_require("virtual-server", "virtual-server-lib.pl");
        $ip = &virtual_server::get_default_ip();
    };
    return $ip if $ip;

    # Fallback: check hostname resolution
    eval {
        my $res = Net::DNS::Resolver->new;
        my $reply = $res->query(&get_system_hostname(), 'A');
        if ($reply) {
            foreach my $rr ($reply->answer) {
                $ip = $rr->address if $rr->type eq 'A';
                last if $ip;
            }
        }
    };
    return $ip || '195.201.245.46'; # last resort fallback
}

sub build_dkim_cnames {
    my ($domain, @tokens) = @_;
    my @records;
    foreach my $token (@tokens) {
        push @records, {
            type => 'CNAME',
            name => "${token}._domainkey.${domain}",
            content => "${token}.dkim.amazonses.com",
        };
    }
    return @records;
}

sub build_spf_record {
    my ($domain) = @_;
    my $ip = get_server_ip();
    my $include = $config{'spf_include'} || 'amazonses.com';
    return "v=spf1 ip4:$ip include:$include ~all";
}

sub build_dmarc_record {
    my ($domain) = @_;
    my $policy = $config{'dmarc_policy'} || 'none';
    my $pct = $config{'dmarc_pct'} || 100;
    my $rua = $config{'dmarc_rua'};

    my $record = "v=DMARC1; p=$policy; pct=$pct";
    $record .= "; rua=mailto:$rua" if $rua;
    return $record;
}

sub merge_spf_record {
    my ($domain, $zone_id) = @_;
    my $ses_include = $config{'spf_include'} || 'amazonses.com';
    my @warnings;

    # Get existing SPF TXT records
    my @txt_records = cf_list_dns_records($zone_id, 'TXT', $domain);
    my @spf_records = grep {
        $_->{content} =~ /^"?v=spf1\s/i
    } @txt_records;

    if (scalar(@spf_records) > 1) {
        push @warnings, "Multiple SPF records found (" . scalar(@spf_records) .
            "). This is a misconfiguration — RFC 7208 requires exactly one.";
    }

    if (@spf_records) {
        my $spf = $spf_records[0];
        my $content = $spf->{content};
        $content =~ s/^"//; $content =~ s/"$//;

        # Already has amazonses.com?
        if ($content =~ /include:\Q$ses_include\E/i) {
            return ('unchanged', $spf->{id}, @warnings);
        }

        # Count DNS lookups
        my $lookup_count = 0;
        $lookup_count++ while $content =~ /\binclude:/gi;
        $lookup_count++ while $content =~ /\ba:/gi;
        $lookup_count++ while $content =~ /\bmx\b/gi;
        $lookup_count++ while $content =~ /\bredirect=/gi;

        if ($lookup_count >= 10) {
            push @warnings, "SPF already has $lookup_count DNS lookups. " .
                "Adding another include will exceed the 10-lookup limit, causing SPF permerror.";
        }

        # Check for redirect=
        if ($content =~ /\bredirect=/) {
            push @warnings, "SPF uses 'redirect=' which changes evaluation. " .
                "Adding include: may not work as expected.";
        }

        # Insert include before the all mechanism
        if ($content =~ s/\s+([\-\~\?\+]all)/ include:$ses_include $1/) {
            my ($data, $err) = cf_update_dns_record(
                $zone_id, $spf->{id}, 'TXT', $domain, $content, 0);
            return $err ? ('error', $err, @warnings)
                       : ('updated', $spf->{id}, @warnings);
        } else {
            # No all mechanism found, append
            $content .= " include:$ses_include ~all";
            my ($data, $err) = cf_update_dns_record(
                $zone_id, $spf->{id}, 'TXT', $domain, $content, 0);
            return $err ? ('error', $err, @warnings)
                       : ('updated', $spf->{id}, @warnings);
        }
    } else {
        # No SPF record exists — create new one
        my $content = build_spf_record($domain);
        my ($data, $err) = cf_create_dns_record(
            $zone_id, 'TXT', $domain, $content, 0);
        return $err ? ('error', $err, @warnings)
                   : ('created', $data->{result}{id}, @warnings);
    }
}

#######################################################################
# Mail Provider Detection (via Net::DNS)
#######################################################################

sub detect_mail_provider {
    my ($domain) = @_;
    my $res = Net::DNS::Resolver->new;
    my $reply = $res->query($domain, 'MX');
    return 'Unknown' unless $reply;

    my @mx;
    foreach my $rr ($reply->answer) {
        push @mx, lc($rr->exchange) if $rr->type eq 'MX';
    }
    return 'No MX' unless @mx;

    my $mx_str = join(' ', @mx);
    my $hostname = lc(&get_system_hostname());

    return 'Local' if $mx_str =~ /\Q$hostname\E/;
    return 'Google Workspace' if $mx_str =~ /google|googlemail/;
    return 'Microsoft 365' if $mx_str =~ /outlook|microsoft/;
    return 'Zoho Mail' if $mx_str =~ /zoho/;
    return 'Rackspace' if $mx_str =~ /mxlogin|emailsrvr/;
    return 'Proofpoint' if $mx_str =~ /pphosted/;

    # Check if MX points to server IP
    my $server_ip = get_server_ip();
    foreach my $m (@mx) {
        my $a_reply = $res->query($m, 'A');
        if ($a_reply) {
            foreach my $rr ($a_reply->answer) {
                return 'Local' if $rr->type eq 'A' && $rr->address eq $server_ip;
            }
        }
    }

    return $mx[0]; # Return raw MX value
}

sub get_dns_provider {
    my ($domain) = @_;
    my $res = Net::DNS::Resolver->new;

    # Walk up to find authoritative NS
    my @parts = split(/\./, $domain);
    for (my $i = 0; $i < scalar(@parts) - 1; $i++) {
        my $try = join('.', @parts[$i..$#parts]);
        my $reply = $res->query($try, 'NS');
        if ($reply) {
            my @ns = map { $_->nsdname }
                     grep { $_->type eq 'NS' } $reply->answer;
            return @ns if @ns;
        }
    }
    return ();
}

#######################################################################
# DNS Backup & Restore
#######################################################################

sub backup_domain_dns {
    my ($domain, $zone_id) = @_;
    &ensure_dirs();

    my %backup;
    $backup{domain} = $domain;
    $backup{timestamp} = time();
    $backup{date} = strftime("%Y-%m-%d %H:%M:%S UTC", gmtime());

    if ($zone_id) {
        # Get SPF records
        my @spf = grep { $_->{content} =~ /v=spf1/i }
                  cf_list_dns_records($zone_id, 'TXT', $domain);
        $backup{spf} = \@spf;

        # Get DMARC records
        my @dmarc = cf_list_dns_records($zone_id, 'TXT', "_dmarc.$domain");
        $backup{dmarc} = \@dmarc;

        # Get existing DKIM CNAME records
        my @dkim = cf_list_dns_records($zone_id, 'CNAME');
        @dkim = grep { $_->{name} =~ /\._domainkey\.\Q$domain\E$/i } @dkim;
        $backup{dkim} = \@dkim;

        $backup{zone_id} = $zone_id;
        $backup{on_cloudflare} = 1;
    } else {
        # Not on Cloudflare — backup via DNS queries
        my $res = Net::DNS::Resolver->new;

        my $spf_reply = $res->query($domain, 'TXT');
        if ($spf_reply) {
            $backup{spf_txt} = [
                map { $_->txtdata }
                grep { $_->type eq 'TXT' && $_->txtdata =~ /v=spf1/i }
                $spf_reply->answer
            ];
        }

        my $dmarc_reply = $res->query("_dmarc.$domain", 'TXT');
        if ($dmarc_reply) {
            $backup{dmarc_txt} = [
                map { $_->txtdata }
                grep { $_->type eq 'TXT' }
                $dmarc_reply->answer
            ];
        }

        $backup{on_cloudflare} = 0;
    }

    my $file = "$BACKUP_DIR/$domain.json";
    &open_tempfile(BACKUP, ">$file");
    &print_tempfile(BACKUP, encode_json(\%backup));
    &close_tempfile(BACKUP);
    chmod(0600, $file);

    return \%backup;
}

sub get_dns_backup {
    my ($domain) = @_;
    my $file = "$BACKUP_DIR/$domain.json";
    return undef unless -f $file;
    my $content = &read_file_contents($file);
    return eval { decode_json($content) };
}

sub restore_domain_dns {
    my ($domain, $zone_id) = @_;
    my $backup = get_dns_backup($domain);
    return (0, "No backup found for $domain") unless $backup;
    return (0, "Domain is not on Cloudflare") unless $zone_id;

    my @errors;

    # Restore SPF
    if ($backup->{spf} && @{$backup->{spf}}) {
        foreach my $rec (@{$backup->{spf}}) {
            my ($action, $id) = cf_ensure_dns_record(
                $zone_id, 'TXT', $rec->{name}, $rec->{content}, 0);
            push @errors, "SPF restore: $id" if $action eq 'error';
        }
    }

    # Restore DMARC
    if ($backup->{dmarc} && @{$backup->{dmarc}}) {
        foreach my $rec (@{$backup->{dmarc}}) {
            my ($action, $id) = cf_ensure_dns_record(
                $zone_id, 'TXT', $rec->{name}, $rec->{content}, 0);
            push @errors, "DMARC restore: $id" if $action eq 'error';
        }
    }

    # Remove SES DKIM CNAMEs (they weren't there before)
    my @dkim_now = cf_list_dns_records($zone_id, 'CNAME');
    foreach my $rec (@dkim_now) {
        if ($rec->{name} =~ /\._domainkey\.\Q$domain\E$/i &&
            $rec->{content} =~ /\.dkim\.amazonses\.com$/i) {
            cf_delete_dns_record($zone_id, $rec->{id});
        }
    }

    return (scalar(@errors) == 0, join('; ', @errors));
}

sub diff_dns_backup {
    my ($domain, $zone_id) = @_;
    my $backup = get_dns_backup($domain);
    return [] unless $backup && $zone_id;

    my @diffs;

    # Compare SPF
    my @current_spf = grep { $_->{content} =~ /v=spf1/i }
                      cf_list_dns_records($zone_id, 'TXT', $domain);
    my $backup_spf = $backup->{spf} || [];

    my $cur_spf_val = @current_spf ? $current_spf[0]{content} : '(none)';
    my $bak_spf_val = @$backup_spf ? $backup_spf->[0]{content} : '(none)';
    if ($cur_spf_val ne $bak_spf_val) {
        push @diffs, { type => 'SPF', backup => $bak_spf_val,
                       current => $cur_spf_val };
    }

    # Compare DMARC
    my @current_dmarc = cf_list_dns_records($zone_id, 'TXT', "_dmarc.$domain");
    my $backup_dmarc = $backup->{dmarc} || [];

    my $cur_dmarc_val = @current_dmarc ? $current_dmarc[0]{content} : '(none)';
    my $bak_dmarc_val = @$backup_dmarc ? $backup_dmarc->[0]{content} : '(none)';
    if ($cur_dmarc_val ne $bak_dmarc_val) {
        push @diffs, { type => 'DMARC', backup => $bak_dmarc_val,
                       current => $cur_dmarc_val };
    }

    return \@diffs;
}

#######################################################################
# Domain State Management
#######################################################################

sub get_domain_state {
    my ($domain) = @_;
    &ensure_dirs();
    my $file = "$STATE_DIR/$domain.json";
    return {} unless -f $file;
    my $content = &read_file_contents($file);
    return eval { decode_json($content) } || {};
}

sub save_domain_state {
    my ($domain, $state) = @_;
    &ensure_dirs();
    my $file = "$STATE_DIR/$domain.json";
    &open_tempfile(STATE, ">$file");
    &print_tempfile(STATE, encode_json($state));
    &close_tempfile(STATE);
    chmod(0600, $file);
}

sub delete_domain_state {
    my ($domain) = @_;
    my $file = "$STATE_DIR/$domain.json";
    unlink($file) if -f $file;
}

sub list_enabled_domains {
    &ensure_dirs();
    my @domains;
    opendir(my $dh, $STATE_DIR) || return ();
    while (my $f = readdir($dh)) {
        next unless $f =~ /^(.+)\.json$/;
        my $domain = $1;
        my $state = get_domain_state($domain);
        push @domains, $domain if $state->{enabled} || $state->{paused};
    }
    closedir($dh);
    return @domains;
}

#######################################################################
# Status Check (per domain)
#######################################################################

sub get_domain_ses_status {
    my ($domain) = @_;

    my %status;
    $status{domain} = $domain;

    # Check domain state
    my $state = get_domain_state($domain);
    $status{enabled} = $state->{enabled} ? 1 : 0;
    $status{paused} = $state->{paused} ? 1 : 0;
    $status{enable_time} = $state->{enable_time} || 0;
    $status{dkim_tokens} = $state->{dkim_tokens} || [];

    # If not enabled and not paused, it's disabled
    unless ($status{enabled} || $status{paused}) {
        $status{overall} = 'DISABLED';
        $status{mail_provider} = detect_mail_provider($domain);
        return \%status;
    }

    # Check SES identity
    my ($ses_data, $ses_err) = ses_get_identity($domain);
    if ($ses_err) {
        $status{ses_exists} = 0;
        $status{ses_error} = $ses_err;
    } else {
        $status{ses_exists} = 1;
        $status{ses_verified} = $ses_data->{VerifiedForSendingStatus} ? 1 : 0;

        if ($ses_data->{DkimAttributes}) {
            $status{dkim_status} = $ses_data->{DkimAttributes}{Status} || 'UNKNOWN';
            $status{dkim_tokens} = $ses_data->{DkimAttributes}{Tokens} || [];
        }
    }

    # Check Cloudflare
    my ($zone_id, $zone_name) = cf_get_zone_for_domain($domain);
    $status{on_cloudflare} = $zone_id ? 1 : 0;
    $status{zone_id} = $zone_id;

    # Check DNS records
    if ($zone_id) {
        # Check DKIM CNAMEs
        my @dkim_ok;
        foreach my $token (@{$status{dkim_tokens}}) {
            my $name = "${token}._domainkey.${domain}";
            my $expected = "${token}.dkim.amazonses.com";
            my @recs = cf_list_dns_records($zone_id, 'CNAME', $name);
            my $found = 0;
            foreach my $r (@recs) {
                $found = 1 if lc($r->{content}) eq lc($expected);
            }
            push @dkim_ok, $found;
        }
        $status{dkim_cnames_ok} = (grep { $_ } @dkim_ok) == scalar(@{$status{dkim_tokens}}) ? 1 : 0;

        # Check SPF
        my $ses_include = $config{'spf_include'} || 'amazonses.com';
        my @spf = grep { $_->{content} =~ /v=spf1/i }
                  cf_list_dns_records($zone_id, 'TXT', $domain);
        $status{spf_ok} = (@spf && $spf[0]{content} =~ /include:\Q$ses_include\E/i) ? 1 : 0;
        $status{spf_record} = @spf ? $spf[0]{content} : '';

        # Check DMARC
        my @dmarc = cf_list_dns_records($zone_id, 'TXT', "_dmarc.$domain");
        $status{dmarc_ok} = @dmarc ? 1 : 0;
        $status{dmarc_record} = @dmarc ? $dmarc[0]{content} : '';
    } else {
        # Use DNS resolver for non-CF domains
        $status{dkim_cnames_ok} = check_dns_dkim($domain, @{$status{dkim_tokens}});
        $status{spf_ok} = check_dns_spf($domain);
        $status{dmarc_ok} = check_dns_dmarc($domain);
    }

    # Mail provider
    $status{mail_provider} = detect_mail_provider($domain);

    # DNS backup exists?
    $status{has_backup} = (-f "$BACKUP_DIR/$domain.json") ? 1 : 0;

    # Determine overall status
    my @issues;
    if ($status{paused}) {
        $status{overall} = 'PAUSED';
    } elsif (!$status{ses_exists}) {
        push @issues, "SES identity missing";
        $status{overall} = 'NEEDS_ATTENTION';
    } elsif (($status{dkim_status} || '') eq 'PENDING') {
        $status{overall} = 'PENDING';
    } elsif (($status{dkim_status} || '') eq 'SUCCESS' &&
             ($status{on_cloudflare} ? 1 : $status{dkim_cnames_ok}) &&
             $status{spf_ok} && $status{dmarc_ok}) {
        $status{overall} = 'READY';
    } elsif (!$status{on_cloudflare}) {
        $status{overall} = 'MANUAL_DNS';
        push @issues, "Domain not on Cloudflare — add DNS records manually";
    } else {
        $status{overall} = 'NEEDS_ATTENTION';
        push @issues, "DKIM CNAMEs missing" unless $status{dkim_cnames_ok};
        push @issues, "SPF record missing or wrong" unless $status{spf_ok};
        push @issues, "DMARC record missing" unless $status{dmarc_ok};
        push @issues, "DKIM failed: " . ($status{dkim_status} || 'unknown')
            if ($status{dkim_status} || '') eq 'FAILED';
    }
    $status{issues} = \@issues;

    return \%status;
}

sub check_dns_dkim {
    my ($domain, @tokens) = @_;
    my $res = Net::DNS::Resolver->new;
    my $ok = 0;
    foreach my $token (@tokens) {
        my $name = "${token}._domainkey.${domain}";
        my $reply = $res->query($name, 'CNAME');
        if ($reply) {
            foreach my $rr ($reply->answer) {
                $ok++ if $rr->type eq 'CNAME' &&
                         $rr->cname =~ /\.dkim\.amazonses\.com$/i;
            }
        }
    }
    return $ok == scalar(@tokens) ? 1 : 0;
}

sub check_dns_spf {
    my ($domain) = @_;
    my $ses_include = $config{'spf_include'} || 'amazonses.com';
    my $res = Net::DNS::Resolver->new;
    my $reply = $res->query($domain, 'TXT');
    return 0 unless $reply;
    foreach my $rr ($reply->answer) {
        next unless $rr->type eq 'TXT';
        return 1 if $rr->txtdata =~ /v=spf1/i &&
                    $rr->txtdata =~ /include:\Q$ses_include\E/i;
    }
    return 0;
}

sub check_dns_dmarc {
    my ($domain) = @_;
    my $res = Net::DNS::Resolver->new;
    my $reply = $res->query("_dmarc.$domain", 'TXT');
    return 0 unless $reply;
    foreach my $rr ($reply->answer) {
        return 1 if $rr->type eq 'TXT' && $rr->txtdata =~ /v=DMARC1/i;
    }
    return 0;
}

#######################################################################
# Postfix Management (per-domain transport maps)
#######################################################################

sub get_ses_smtp_endpoint {
    my $region = $config{'aws_region'} || 'eu-west-1';
    return "email-smtp.$region.amazonaws.com";
}

sub configure_postfix_ses {
    # One-time Postfix setup for per-domain SES routing
    # Backs up main.cf first
    &ensure_dirs();

    my $backup_file = "$BACKUP_DIR/main.cf.pre-ses";
    unless (-f $backup_file) {
        system("cp /etc/postfix/main.cf $backup_file");
        chmod(0600, $backup_file);
    }

    my $endpoint = get_ses_smtp_endpoint();
    my $smtp_pass = ses_derive_smtp_credentials(
        $config{'aws_secret_key'}, $config{'aws_region'});
    my $smtp_user = $config{'aws_access_key'};

    # Create sasl_passwd
    &open_tempfile(SASL, ">$SASL_PASSWD");
    &print_tempfile(SASL, "[$endpoint]:587 $smtp_user:$smtp_pass\n");
    &close_tempfile(SASL);
    chmod(0600, $SASL_PASSWD);
    system("postmap $SASL_PASSWD");

    # Create empty transport map if not exists
    unless (-f $TRANSPORT_MAP) {
        &open_tempfile(TMAP, ">$TRANSPORT_MAP");
        &print_tempfile(TMAP,
            "# Managed by virtualmin-ses plugin - do not edit manually\n");
        &close_tempfile(TMAP);
        system("postmap $TRANSPORT_MAP");
    }

    # Add Postfix settings
    my @needed = (
        ['sender_dependent_relayhost_maps', "hash:$TRANSPORT_MAP"],
        ['smtp_sasl_auth_enable', 'yes'],
        ['smtp_sasl_password_maps', "hash:$SASL_PASSWD"],
        ['smtp_sasl_security_options', 'noanonymous'],
    );

    foreach my $pair (@needed) {
        my ($key, $val) = @$pair;
        my $current = `postconf -h $key 2>/dev/null`;
        chomp $current;
        if ($current ne $val) {
            system("postconf -e '$key=$val'");
        }
    }

    # Reload Postfix
    system("systemctl reload postfix 2>/dev/null || postfix reload 2>/dev/null");

    $config{'postfix_configured'} = 1;
    &save_module_config(\%config);

    return 1;
}

sub add_domain_to_transport {
    my ($domain) = @_;
    my $endpoint = get_ses_smtp_endpoint();
    my $entry = "\@$domain";

    # Read current map
    my @lines;
    if (-f $TRANSPORT_MAP) {
        open(my $fh, '<', $TRANSPORT_MAP);
        @lines = <$fh>;
        close($fh);
    }

    # Check if already present
    my $found = 0;
    foreach my $line (@lines) {
        if ($line =~ /^\@\Q$domain\E\s/) {
            $found = 1;
            last;
        }
    }

    unless ($found) {
        &open_tempfile(TMAP, ">>$TRANSPORT_MAP");
        &print_tempfile(TMAP, "$entry\t[$endpoint]:587\n");
        &close_tempfile(TMAP);
    }

    system("postmap $TRANSPORT_MAP");
    system("systemctl reload postfix 2>/dev/null || postfix reload 2>/dev/null");
    return 1;
}

sub remove_domain_from_transport {
    my ($domain) = @_;
    return unless -f $TRANSPORT_MAP;

    open(my $fh, '<', $TRANSPORT_MAP);
    my @lines = <$fh>;
    close($fh);

    my @new_lines = grep { $_ !~ /^\@\Q$domain\E\s/ } @lines;

    &open_tempfile(TMAP, ">$TRANSPORT_MAP");
    foreach my $line (@new_lines) {
        &print_tempfile(TMAP, $line);
    }
    &close_tempfile(TMAP);

    system("postmap $TRANSPORT_MAP");
    system("systemctl reload postfix 2>/dev/null || postfix reload 2>/dev/null");
    return 1;
}

sub remove_all_from_transport {
    # Emergency: clear all entries
    &open_tempfile(TMAP, ">$TRANSPORT_MAP");
    &print_tempfile(TMAP,
        "# Managed by virtualmin-ses plugin - do not edit manually\n");
    &print_tempfile(TMAP, "# Emergency cleared at " .
        strftime("%Y-%m-%d %H:%M:%S", localtime()) . "\n");
    &close_tempfile(TMAP);

    system("postmap $TRANSPORT_MAP");
    system("systemctl reload postfix 2>/dev/null || postfix reload 2>/dev/null");
    return 1;
}

sub restore_postfix_backup {
    my $backup_file = "$BACKUP_DIR/main.cf.pre-ses";
    return (0, "No Postfix backup found") unless -f $backup_file;

    system("cp $backup_file /etc/postfix/main.cf");
    system("systemctl reload postfix 2>/dev/null || postfix reload 2>/dev/null");
    return (1, undef);
}

sub get_postfix_ses_status {
    my %status;
    my $routing = `postconf -h sender_dependent_relayhost_maps 2>/dev/null`;
    chomp $routing;
    $status{routing_configured} = ($routing =~ /ses_relayhost/) ? 1 : 0;

    my $sasl = `postconf -h smtp_sasl_auth_enable 2>/dev/null`;
    chomp $sasl;
    $status{sasl_configured} = ($sasl eq 'yes') ? 1 : 0;

    my $tls = `postconf -h smtp_tls_security_level 2>/dev/null`;
    chomp $tls;
    $status{tls_level} = $tls;

    $status{dane_preserved} = ($tls eq 'dane') ? 1 : 0;
    $status{backup_exists} = (-f "$BACKUP_DIR/main.cf.pre-ses") ? 1 : 0;

    # Count domains in transport map
    $status{domain_count} = 0;
    if (-f $TRANSPORT_MAP) {
        open(my $fh, '<', $TRANSPORT_MAP);
        while (<$fh>) { $status{domain_count}++ if /^\@/; }
        close($fh);
    }

    return \%status;
}

#######################################################################
# OpenDKIM Management
#######################################################################

sub disable_opendkim_for_domain {
    my ($domain) = @_;
    my $signing_table = '/etc/dkim-signingtable';
    return unless -f $signing_table;

    open(my $fh, '<', $signing_table);
    my @lines = <$fh>;
    close($fh);

    my @new_lines = grep { $_ !~ /\*\@\Q$domain\E\s/ } @lines;

    if (scalar(@new_lines) != scalar(@lines)) {
        &open_tempfile(DKIM, ">$signing_table");
        foreach my $line (@new_lines) {
            &print_tempfile(DKIM, $line);
        }
        &close_tempfile(DKIM);

        # Reload OpenDKIM
        system("systemctl reload opendkim 2>/dev/null");
    }
}

sub restore_opendkim_for_domain {
    my ($domain) = @_;
    my $signing_table = '/etc/dkim-signingtable';
    my $key_table = '/etc/dkim-keytable';

    # Determine the key to use (default key)
    my $key_name = 'default';
    if (-f $key_table) {
        open(my $fh, '<', $key_table);
        while (<$fh>) {
            if (/^(\S+)\s/) { $key_name = $1; last; }
        }
        close($fh);
    }

    # Check if entry already exists
    if (-f $signing_table) {
        open(my $fh, '<', $signing_table);
        while (<$fh>) {
            return if /\*\@\Q$domain\E\s/;
        }
        close($fh);
    }

    # Add entry
    &open_tempfile(DKIM, ">>$signing_table");
    &print_tempfile(DKIM, "*\@$domain\t$key_name\n");
    &close_tempfile(DKIM);
    system("systemctl reload opendkim 2>/dev/null");
}

#######################################################################
# Test Email & Log Viewer
#######################################################################

sub send_test_email {
    my ($from_domain, $to_address) = @_;
    my $from = "test\@$from_domain";
    my $subject = "SES Test from $from_domain - " . strftime("%H:%M:%S", localtime());
    my $body = "This is a test email sent from the Virtualmin SES plugin.\n" .
               "Domain: $from_domain\n" .
               "Time: " . strftime("%Y-%m-%d %H:%M:%S %Z", localtime()) . "\n";

    my $cmd = "echo '$body' | mail -s '$subject' -r '$from' '$to_address' 2>&1";
    my $output = `$cmd`;
    my $exit_code = $? >> 8;

    # Wait briefly and check mail log
    sleep(2);
    my @log = get_recent_mail_log($from_domain, 5);

    return {
        success => ($exit_code == 0) ? 1 : 0,
        output => $output,
        log => \@log,
    };
}

sub get_recent_mail_log {
    my ($domain, $count) = @_;
    $count ||= 20;

    my @entries;
    my $log_file = '/var/log/maillog';
    return @entries unless -f $log_file;

    # Read last 500 lines and filter
    my @lines = split(/\n/, `tail -500 $log_file`);

    foreach my $line (reverse @lines) {
        last if scalar(@entries) >= $count;

        if ($domain) {
            next unless $line =~ /\Q$domain\E/i;
        }

        # Parse key fields
        if ($line =~ /(\w+\s+\d+\s+[\d:]+)\s+\S+\s+postfix\/(\w+)\[.*?:\s+(.*)/) {
            my ($timestamp, $component, $detail) = ($1, $2, $3);
            my %entry = (
                timestamp => $timestamp,
                component => $component,
                detail => $detail,
            );

            # Extract status
            if ($detail =~ /status=(\w+)/) {
                $entry{status} = $1;
            }
            if ($detail =~ /to=<([^>]+)>/) {
                $entry{to} = $1;
            }
            if ($detail =~ /from=<([^>]+)>/) {
                $entry{from} = $1;
            }
            if ($detail =~ /relay=([^\s,]+)/) {
                $entry{relay} = $1;
            }

            push @entries, \%entry;
        }
    }

    return @entries;
}

#######################################################################
# Virtualmin Domain List Helper
#######################################################################

sub get_virtualmin_domains {
    my @domains;
    eval {
        &foreign_require("virtual-server", "virtual-server-lib.pl");
        foreach my $d (&virtual_server::list_domains()) {
            push @domains, {
                dom => $d->{'dom'},
                user => $d->{'user'},
                home => $d->{'home'},
                alias => $d->{'alias'} ? 1 : 0,
            };
        }
    };
    if ($@) {
        # Fallback to CLI
        my @names = split(/\n/, `virtualmin list-domains --name-only 2>/dev/null`);
        @domains = map { { dom => $_, alias => 0 } } @names;
    }
    return @domains;
}

1;
