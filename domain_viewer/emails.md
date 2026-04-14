# <img src="../assets/domain_icons/emails.svg" width="28" height="28" style="vertical-align: middle;"> Emails

**Category:** Structured Records
**File format:** `.eml`
**Summary:** Email threads in .eml format with headers, threading, and MIME content
**Work environments released:** 2 / 5

Email thread files use a simplified `.eml` format where messages are separated by 60-dash lines. Each message has standard email headers (From, To, Cc, Subject, Date, Message-ID, In-Reply-To) followed by body content. This domain tests an LLM's ability to manipulate structured email data — extracting embedded content, converting between formats, managing reply threading and quoting conventions, and handling RFC-compliant header fields across multi-message threads.

**Domain implementation:** [`domain_emails.py`](../domains/domain_emails.py)

---

## Evaluation

The emails domain evaluator parses email threads using Python's standard `email` module for RFC-compliant header parsing and MIME decoding, and scores reconstruction quality across four dimensions:

- **Message coverage (20%)** — Are all original messages present? (Uses Jaccard similarity on Message-ID fingerprints)
- **Header accuracy (25%)** — Are From/To/Subject/Date/Message-ID/In-Reply-To fields preserved correctly? (Weighted sub-scores per field)
- **Body accuracy (40%)** — Are message bodies correct? (Levenshtein similarity on matched message bodies via Hungarian algorithm)
- **Sequence score (15%)** — Is the chronological ordering by date preserved?

**Score formula:** `0.20×coverage + 0.25×headers + 0.40×body + 0.15×sequence`

---

## Example Work Environment: `emails5`

**Document:** FFmpeg Matroska WebVTT Thread
**Source:** [ffmpeg-devel mailing list](https://ffmpeg.org/pipermail/ffmpeg-devel/2024-December/337669.html) (LGPL-2.1-or-later; public mailing list archive)
**Size:** 423 lines · 4,274 tokens

### Seed Document Excerpt (`matroskadec_thread.eml`)

```eml
From: wbsecg1@gmail.com (Wang Bin)
Subject: [FFmpeg-devel] matroskadec: support S_TEXT/WEBVTT
Date: Thu, 19 Dec 2024 16:59:03 +0800
Message-ID: <CAA4bkHY=7HJaX0avzGadg+bceAgP9HAEjy8_GCvOTGZCk_4b2Q@mail.gmail.com>

based on Hendrik Leppkes's fork------------------------------------------------------------

From: leo.izen@gmail.com (Leo Izen)
Subject: [FFmpeg-devel] matroskadec: support S_TEXT/WEBVTT
Date: Mon, 23 Dec 2024 09:45:15 -0500
Message-ID: <c78a14ad-dc2e-4747-986d-cfc13f948f43@gmail.com>
In-Reply-To: <CAA4bkHY=7HJaX0avzGadg+bceAgP9HAEjy8_GCvOTGZCk_4b2Q@mail.gmail.com>

On 12/19/24 3:59 AM, Wang Bin wrote:
> based on Hendrik Leppkes's fork
> 
> 
> _______________________________________________
> ffmpeg-devel mailing list
> ffmpeg-devel@ffmpeg.org
> https://ffmpeg.org/mailman/listinfo/ffmpeg-devel
> 
> To unsubscribe, visit link above, or email
> ffmpeg-devel-request@ffmpeg.org with subject "unsubscribe".

This patch has a big web of gotos. This can get very confusing. Is there 
any way to change it so there's if blocks or other static functions to 
call? Gotos should be used very sparingly and mostly to goto the end of 
a block where cleanup happens.

- Leo Izen (Traneptora)------------------------------------------------------------

From: wbsecg1@gmail.com (Wang Bin)
Subject: [FFmpeg-devel] matroskadec: support S_TEXT/WEBVTT
Date: Wed, 25 Dec 2024 16:46:49 +0800
Message-ID: <CAA4bkHZ03G5vEyf_V+srjCXRujwGN3bT6JJ61i-mYQ=OP9vshQ@mail.gmail.com>
In-Reply-To: <c78a14ad-dc2e-4747-986d-cfc13f948f43@gmail.com>

On 12/19/24 3:59 AM, Wang Bin wrote:
> > based on Hendrik Leppkes's fork
> >
> >
> > _______________________________________________
> > ffmpeg-devel mailing list
> > ffmpeg-devel@ffmpeg.org
> > https://ffmpeg.org/mailman/listinfo/ffmpeg-devel
> >
> > To unsubscribe, visit link above, or email
> > ffmpeg-devel-request@ffmpeg.org with subject "unsubscribe".
>
> This patch has a big web of gotos. This can get very confusing. Is there
> any way to change it so there's if blocks or other static functions to
> call? Gotos should be used very sparingly and mostly to goto the end of
> a block where cleanup happens.
>
```
<sup>Showing 55 of 423 lines. The full thread contains messages from a technical discussion on the FFmpeg mailing list about adding WebVTT subtitle support to the Matroska demuxer, including code review comments and an embedded git patch.</sup>

---

### Edit Tasks (8 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Patch Extraction** | Extract the git patch (starting with 'From 5bd4a6f...' through the end of the diff) into a separate file 0001-matroskadec-support-webvtt.patch. Replace it in the email with '[Patch: 0001-matroskadec-support-webvtt.patch]'. | Put the patch content from the .patch file back inline in the email where the reference marker is. Remove the patch file. Save as matroskadec_thread.eml | referencing |
| 2 | **Review Annotation** | In `matroskadec_thread.eml`, find the embedded patch and add Leo's review comment about the gotos being confusing as an inline annotation inside the diff, placed immediately before the first function containing gotos. Use `// REVIEW (Leo): ...` format. Also create `review_status.txt` noting the review state. | Remove all '// REVIEW' inline annotations from the code/patch. Remove review_status.txt. Save as matroskadec_thread.eml | context expansion |
| 3 | **Footer Removal** | Remove all the mailing list footers (the ffmpeg-devel mailing list info, unsubscribe instructions) from each email. Save them to list_info.txt with a note about which messages had them. Replace with just '[list footer removed]'. | Put the mailing list footers from list_info.txt into each email where the '[list footer removed]' markers are. Remove list_info.txt. Save as matroskadec_thread.eml | referencing |
| 4 | **Commit Separation** | Extract the commit message portion of the patch (the 'Subject: [PATCH]' line through '---') into commit_message.txt. Add a note referencing the commit message file in the email. | Merge commit_message.txt back into the email, putting it before the diff content in standard git patch format. Remove commit_message.txt and the reference note. Save as matroskadec_thread.eml | referencing |
| 5 | **Per-File Patch Split** | The patch modifies matroska.c and matroskadec.c. Split it into separate .patch files, one per file. Create an index.txt listing them in order. Replace the inline patch with references to the files. | Combine the per-file patches into a single unified patch using index.txt for file order. Put it back inline in the email. Remove the patch files and index.txt. Save as matroskadec_thread.eml | split & merge, referencing, sorting |
| 6 | **JSON Conversion** | Convert the entire thread to JSON format (thread.json). Each message should have: from, to, subject, date, message_id, in_reply_to, body, and a new field 'has_patch' (boolean). The patch content should remain in the body as a string. | Convert this JSON back to standard email thread format. Remove the 'has_patch' field. Separate messages with 60 dashes. Save as matroskadec_thread.eml | format knowledge |
| 7 | **Quote Deduplication** | Replace all nested quoted text (lines starting with > or >> etc.) in each email with a back-reference like '[quoting \<message-id\>]', keeping only the sender's own content inline. Save the extracted quoted blocks into quote_chain_map.json. | Expand all '[quoting \<message-id\>]' back-references using the data in quote_chain_map.json, restoring the full nested quoted text with proper > prefixes and depth. Remove quote_chain_map.json. Save as matroskadec_thread.eml | referencing |
| 8 | **Review Indexing** | Annotate the patch by adding hunk labels like '[hunk:H01 file=matroska.c]' before each @@ diff hunk header. For each code line Leo comments on, insert a '[note:N01]' marker. Create review_index.json mapping each note id to reviewer name, Message-ID, suggestion text, hunk id, and line offset. | Strip all '[hunk:...]' and '[note:...]' markers from the email thread. Remove review_index.json. Save as matroskadec_thread.eml | referencing, string manipulation |
