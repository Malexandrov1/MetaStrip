# Security and privacy

MetaStrip processes files locally. It has no upload endpoint, accounts, analytics,
advertising, automatic tool downloads, or runtime update checks. Inspection values
are shown only when requested. Optional history records operational results, not
the values of removed metadata. Filenames and output paths in history can themselves
be sensitive: keep history disabled when those records are unnecessary.

## Scope of verification

Verification is limited to the implemented parsers, supported structures, and
configured checks. A successful check does not prove the absence of all identifying
information. Visible content, faces, watermarks, audio, steganography, custom binary
payloads, and metadata inside compressed media bitstreams are outside the scope of
general metadata cleanup. Retained color profiles and technical fields can identify
software or equipment. Examine the per-file warning and verification report.

PDF cleanup is not complete anonymization. Readable page content, fonts, forms,
links, bookmarks, and other structures can contain identifying information. Digital
signatures cannot survive a document rewrite as valid signatures. Do not use the
application to make claims of forensic anonymity or secure redaction.

## File handling

Originals are opened for reading. Sanitization creates a temporary output beside
the intended destination, validates it, and publishes a uniquely named copy without
replacing an existing file. Cancellation and ordinary errors remove temporary
outputs. A forced process termination or power loss can leave temporary artifacts;
inspect the output directory before sharing its contents. Temporary outputs may
contain metadata until processing finishes. Deleting a file is not secure erasure.

Untrusted files are parsed by native libraries and external programs. Keep those
dependencies up to date. MetaStrip is not a sandbox for malicious documents. Use
normal operating-system isolation when handling files from untrusted senders.
External tools are resolved locally and invoked with argument lists, timeouts, and
without a command shell. Only configure trusted executables and directories.

## Reporting an issue

Do not attach private files or metadata to public issues. Start with a minimal
synthetic fixture and describe the affected version, format, configured checks,
and dependency versions. For a vulnerability, use **Report a vulnerability**
in GitHub’s Security tab once private reporting is enabled. Until then, contact
the maintainer privately.
