# Security

## Threat model

This project reads web pages it does not control (`wdfw.wa.gov`, `data.wa.gov`, two
WDFW ArcGIS servers), turns links on those pages into filenames on your computer,
downloads files, parses them, and builds an HTML page you open in your browser.

The untrusted side of that boundary is everything those servers return — and by
extension anyone who can tamper with them: a compromised CMS, a hijacked DNS answer,
a proxy on a café or hotel network.

The design rule is that **nothing on the far side of that boundary may choose where a
file lands, which host is contacted, how much is read, or what code runs.**

Nothing here handles credentials, and the dashboard stores nothing in your browser.

---

## What enforces that

### Network — `src/safety.py`

* **Host allow-list.** Only `wdfw.wa.gov`, `data.wa.gov`,
  `geodataservices.wdfw.wa.gov` and `services3.arcgis.com` may be contacted. Every
  entry is a deliberate decision; adding one widens the attack surface of every
  update run.
* **HTTPS only**, including after redirects. `urllib` follows redirects anywhere by
  default, so a `302` to `http://attacker.example` would otherwise be fetched
  silently. `_StrictRedirectHandler` re-checks every hop against the same allow-list
  and refuses anything else. A look-alike host such as `wdfw.wa.gov.evil.com` fails
  the check, because the comparison is on the parsed hostname, not a substring.
* **Size ceiling.** Responses are read in 64 KB chunks and abandoned the moment they
  exceed the cap, and a declared `Content-Length` over the cap is refused before a
  byte is read. A hostile or broken server cannot exhaust memory or fill the disk.

### Files — `src/safety.py`

* **`safe_filename()`** decodes percent-encoding *repeatedly first* — decoding after
  sanitising is how `..%2f..%2f` turns back into a traversal — then strips NULs,
  takes the basename, and reduces what is left to `[A-Za-z0-9._-]`. Windows device
  names (`CON`, `PRN`, `LPT1`…) are prefixed so they cannot be created either.
* **`resolve_within()`** re-resolves the joined path and refuses to return it unless
  it is genuinely inside the intended folder. Every report download goes through it,
  so a crafted link on a tampered page cannot write outside `.cache/`.
* **Content sniffing.** A downloaded report is only kept if it actually begins with
  `%PDF`. A link that has been repointed at something else is skipped and reported.
* **Decompression bound.** The gzipped data files are read through a bounded reader
  that raises rather than expanding past half a gigabyte, so a tampered `.csv.gz` in
  a fork cannot be a decompression bomb.

### Dependencies

`requirements.lock.txt` pins the whole tree by SHA-256, and both the launchers and CI
install with `--require-hashes`. There is deliberately no fallback to the unpinned
`requirements.txt`: if the verified install fails, the right outcome is to stop, not
to quietly install whatever is newest on PyPI.

The only third-party package is `pdfplumber`, and it is needed for two of the seven
sources. Everything else — every HTTP request, every HTML and JSON parse, the whole
dashboard — is standard library and hand-written.

### The built page

* A restrictive **Content-Security-Policy** meta tag: `default-src 'none'`, no
  external scripts, styles, images or fonts, no form submission, no base URI. The
  page cannot phone home, and there is nothing for it to phone home with.
* The data is injected as **JSON inside a `<script type="application/json">` block**
  and read with `JSON.parse`. There is no `eval`, no `innerHTML` of untrusted values
  without escaping, and no template that turns data into code.
* `</` inside the payload is escaped at build time (`assemble.py`), so a location
  name containing `</script>` cannot close the block early.
* Every value that reaches the DOM through `innerHTML` goes through `escapeHtml()`
  first. Place names come from WDFW pages and are treated as untrusted text.

### The unattended job

The daily GitHub Actions refresh has `contents: write`, so it is the most valuable
thing here to an attacker. Two things constrain it:

* Actions are **pinned to commit SHAs**, not tags. A tag like `@v4` is mutable and can
  be repointed at new code by whoever controls that repository.
* The job **refuses to commit anything outside `data/` and `docs/`**. A refresh that
  somehow modified code would fail rather than push.

---

## Residual risks, stated plainly

* **The data itself is trusted.** If WDFW publishes a wrong number, this repository
  will faithfully reproduce it. The audit in `src/validate.py` catches internal
  contradictions and disagreements with WDFW's own summary table, not errors WDFW
  made consistently.
* **The prose parser can be wrong without being unsafe.** The Columbia report is read
  from sentences; a sentence shaped in a way the parser does not expect contributes
  nothing, and one shaped misleadingly could contribute a wrong figure. This is a
  correctness risk, not a security one, and it is why that source's coverage is
  counted and printed on every run.
* **Approximate coordinates are approximate.** The hand-placed positions in
  `src/geo.py` are for places with no WDFW point dataset. They are labelled as such
  everywhere they appear.

---

## Reporting

Open an issue, or email the address on the repository owner's GitHub profile. If the
finding is a way to make this project write outside its own folder, contact a host
that is not on the allow-list, or execute anything from a downloaded report, please
say so in the first line so it can be prioritised.
