# Welcome and architecture visual polish — V49, 7 October 2026

User requested a fuller initial screen, a clear attractive architecture diagram,
and modest color/typography refinement. No GitHub push or deployment authorized.

Empty Overview now has a responsive gradient welcome panel, selection prompt,
saved-company count and three exploration cards. Failure states retain explicit
messages rather than displaying the welcome panel as if results were loaded.
Main title/headings use navy/blue; secondary text uses muted slate. Risk colors
retain red, green and gray. No distracting scrolling text or script required.

How it works now shows a nine-stage SVG architecture diagram as an image:
Companies House -> R2 -> extraction -> Turso facts -> reference beliefs -> ER
-> Turso results -> Streamlit UI -> Community Cloud target. Governance API
facts have a direct dashed link into Turso. This is a genuine linked diagram,
not an HTML block of text. Rendering via st.image avoids HTML SVG sanitization.
The diagram was rendered to PNG and visually inspected for clipping/readability.

No YAML/model, source, snapshot or database changes. V48 snapshot fingerprints
remain valid. Users who completed V48 preparation only need install/restart.
Otherwise run prepare_dashboard.py once as documented in V48.

Verification: 899 tests passed; git diff --check clean. Architecture image and
semantic node/link regression added. Existing missing data, connection-failure,
no-selection, saved-result and no-write tests retained. Installer byte-verified.
No live Turso access, Git commit/push or public hosting performed.

Next: user reviews appearance and five company results. GitHub release and
Streamlit Community Cloud deployment remain gated on user acceptance.
