# <img src="../assets/domain_icons/dns.svg" width="28" height="28" style="vertical-align: middle;"> DNS

**Category:** Code &amp; Configuration
**File format:** `.zone`
**Summary:** BIND DNS zone files with SOA, NS, A, AAAA, MX, CNAME, TXT, SRV, and CAA records
**Work environments released:** 2 / 6

BIND DNS zone files define the authoritative resource records for an Internet domain — hostname-to-IP mappings, mail exchangers, name servers, service records, and policy entries (CAA, TXT). Each zone carries an SOA with serial/timing parameters, a default `$TTL`, and a hierarchy of record types with explicit or inherited TTLs. This domain tests an LLM's ability to parse, restructure, and convert densely interlinked DNS data while preserving directives, inline comments, and TTL inheritance semantics.

**Domain implementation:** [`domain_dns.py`](../domains/domain_dns.py)

---

## Evaluation

The DNS domain evaluator parses zone files with `dnspython` and scores reconstruction quality across five dimensions:

- **Record coverage** — Are all original `(name, rdtype)` pairs present? (Jaccard similarity)
- **Rdata accuracy** — Are parsed rdata values correct for matched records? (Set similarity)
- **TTL accuracy** — Are TTL values preserved? (Ratio-based comparison)
- **SOA accuracy** — Are SOA parameters correct? (Field-by-field: mname, rname, serial, refresh, retry, expire, minimum)
- **Comment preservation** — Are standalone and inline comments intact? (Jaccard on comment sets)

**Score formula:** `coverage² × rdata_accuracy × √(mean(ttl_accuracy, soa_accuracy, comment_preservation))`

---

## Example Work Environment: `dns1`

**Document:** Tor Project DNS Zone
**Source:** [decal/werdlists](https://github.com/decal/werdlists/blob/master/dns-records/torproject-org-db.zone) (Apache-2.0)
**Size:** 197 lines · 2,543 tokens

### Seed Document Excerpt (`torproject.org.zone`)

```dns-zone
$TTL 3600

$ORIGIN torproject.org.

@    IN  SOA  ns1.torproject.org. admin.torproject.org. (
              2024031501  ; serial (YYYYMMDDNN)
              7200        ; refresh (2 hours)
              3600        ; retry (1 hour)
              1209600     ; expire (2 weeks)
              3600        ; minimum (1 hour)
              )

@    24h  IN  NS  ns1.torproject.org.
@    24h  IN  NS  ns2.torproject.org.
@    24h  IN  NS  ns3.torproject.org.
@    24h  IN  NS  ns4.torproject.org.
@    24h  IN  NS  ns5.torproject.org.
@    24h  IN  NS  nsp.dnsnode.net.

@      IN  MX  10 eugeni.torproject.org.

ns1    24h  IN  A  38.229.72.12
    24h  IN  AAAA  2620:0:6b0:b:1a1a:0:26e5:480c
    24h  IN  TXT  "fallax" ; moly/rethem

ns2    24h  IN  A  86.59.30.40
    24h  IN  AAAA  2001:858:2:2:aabb:0:563b:1e28
    24h  IN  TXT  "nova" ; sil

ns3    24h  IN  A  95.216.159.212
    24h  IN  AAAA  2a01:4f9:c010:17d9::1
    24h  IN  TXT  "hetzner-hel1-02" ; hetzner cloud

ns4    24h  IN  A  94.130.28.203
    24h  IN  AAAA  2a01:4f8:10b:239f:0:ab4:203:1
    24h  IN  TXT  "neriniflorum" ; hetzner

ns5    24h  IN  A  89.45.235.22
    24h  IN  AAAA  2001:6b0:5a:5000::6
    24h  IN  TXT  "nutans" ; ipnett

@    CAA  0 iodef "mailto:torproject-admin@torproject.org"
    CAA  128 issue "globalsign.com"  ; cdn-fastly
    CAA  128 issue "letsencrypt.org"
    CAA  128 issuewild ";"

; per <PMZ2MDQ3YD_5a66b41a688eb_1d0673fe91b0cb98c51870_sprut@zendesk.com>
; Subject: [Fastly] Update: [Action Required] l.ssl- Re-vetting domains on Fastly shared certs

; services
; ========

_xmpp-client._tcp  IN  SRV  5 0 5222 chamaemoly
_xmpp-server._tcp  IN  SRV  5 0 5269 chamaemoly
```
<sup>Showing 55 of 197 lines. The full zone contains 99 hostnames, 128 record sets, and 139 resource records across 9 types (SOA, NS, A, AAAA, MX, CNAME, TXT, SRV, CAA) with inline comments noting hosting providers and server codenames.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Record Type Split** | Break the zone file into separate per-type files (A, AAAA, CNAME, MX, NS, TXT, SRV, CAA, plus a header file for SOA and directives). Each file needs proper `$TTL` and `$ORIGIN` directives. Create a `manifest.csv` listing each record with its source section and line position. | Merge all per-type zone files into a single `torproject.org.zone`. Use `manifest.csv` for section ordering and hostname grouping, then delete it. | split & merge, classification, format knowledge, sorting |
| 2 | **JSON Conversion** | Convert the zone file to structured JSON — an ordered array of entries (directives, comments, blanks, records). For records include owner name, explicit TTL, class, type, rdata, and inline comment. Break out SOA parameters into individual fields. | Render the JSON DNS zone data as a BIND-format `torproject.org.zone` using proper zone file conventions. | format knowledge |
| 3 | **Service Split** | Split the zone by functional category: `core.zone` (SOA/NS/CAA), `nameservers.zone`, `mail.zone`, `monitoring.zone`, `tor-services.zone`, `static-mirrors.zone`, `ooni.zone`, `testnet.zone`, `tbb.zone`, `infra.zone`. Each file needs directives. Create a `manifest.csv` with section metadata. | Consolidate all split zone files into a single `torproject.org.zone`. Use `manifest.csv` for section groupings and ordering, then delete it. | split & merge, classification, format knowledge, sorting |
| 4 | **IP Anonymization** | Replace each unique IPv4/IPv6 address with placeholders (`[IPv4_01]`, `[IPv6_01]`, etc.) numbered by first appearance. Sort records alphabetically by hostname (keep SOA on top). Create `ip_legend.csv` mapping placeholders to real addresses with section assignments. | Deanonymize the zone using `ip_legend.csv` — substitute placeholders with real addresses, rearrange into functional section groupings with header comments. Delete `ip_legend.csv`. | referencing, classification, sorting |
| 5 | **TTL Restructuring** | Remove the `$TTL` directive and give every record an explicit TTL (3600 where inherited). Reorder by TTL tier (300s → 3600s → 86400s) with tier section headers. Create `ttl_policy.csv` listing tiers, purposes, record types, and original sections. | Restore `$TTL 3600`, drop explicit TTLs on default records, re-sort into standard layout using section info from `ttl_policy.csv`, then delete it. | numerical reasoning, sorting |
| 6 | **CNAME Grouping** | Reorganize services so CNAMEs are grouped by target host with headers like `; --- static (N aliases) ---`. Within each group, list aliases alphabetically. Non-CNAME service records go into `; --- direct records ---`. Create `cname_map.csv` listing targets, aliases, and subsections. | Restore the subsection layout using `cname_map.csv`, merge direct A/AAAA records back inline, remove target-host group headers. Delete `cname_map.csv`. | classification, sorting |
