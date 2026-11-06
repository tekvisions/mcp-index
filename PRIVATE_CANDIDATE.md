Historical discovery remediation candidate
=========================================

This was the incomplete 1,813-record local candidate before full capture and
release integration. It is not the current publication status. The reviewed
replacement was released on 2026-11-06; see RELEASE_ACCEPTANCE.md. The original
candidate limits below are retained rather than presented as current facts.

The public MCP release remains held by MCP_PUBLICATION_HOLD.md and release_guard.py. The legacy scheduled refresh and deployment controls are unchanged.

This branch fixes guessed install coordinates and placeholder endpoints, adds source-HTML catalog pagination and a raw-data hash check before client rendering, aligns the candidate method copy with registry timestamps, and stops the detail renderer from deleting previous routes. All generation was tested in a private local output folder; no Vercel deployment or IndexNow request was made for this candidate.

The saved 1,813-record data.json has no full-source completeness receipt. The source contains 2,285 previous detail paths; the candidate union contains 3,891 paths, including 2,078 prior paths absent from this data snapshot. Retention review and integration of a current cursor-complete collection into a bounded package remain release requirements. The separate 3 November diagnostic capture is evidence about traversal, not acceptance of this candidate.

The private candidate is not a substitute for satisfying the publication hold. Do not deploy it or remove the hold solely because local tests pass.
