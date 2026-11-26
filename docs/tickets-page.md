# Tickets page

Work for `frontend/src/pages/TicketsPage.tsx`. A ticket here is the product shape: `context` is what is wrong, `expected` is the behaviour that should hold. There is no acceptance-criteria field.

## T1. The form takes the page

Severity: high

Context: The larger column is three textareas, 6, 10, and 8 rows. The ticket list is the smaller column. Resolve tickets sits under all of that, so on a laptop it is below the fold. After tickets exist, the form stays full size and the board never becomes the page.

Expected: Once tickets exist, the board is the main surface. Intake can be opened without occupying the whole screen. The resolve action stays visible without scrolling past the empty textareas.

## T2. The fields do not say what they are

Severity: high

Context: The first control is labeled Email and is a notes box. The placeholder says "evaluator email or defect notes." Project context is optional only inside the placeholder, which disappears as soon as you type. All three fields share the same underline and the same uppercase label, so nothing shows which one the run needs.

Expected: Each field is named for what the user pastes. Required and optional stay visible outside the placeholder. The three fields are not the same visual weight.

## T3. The PDF control is a pill doing three jobs

Severity: medium

Context: Upload or Drop PDF here is the mode switch, the file button, and the drop target. Choose PDF with no file selected and the area under the pills is empty. The file input is removed from the keyboard.

Expected: Paste and PDF are separate choices. The drop area is visible in PDF mode before a file is chosen. A keyboard user can open the file picker.

## T4. A ticket row hides the ticket

Severity: high

Context: The row shows an id, a title, a status word, and two lines of context. Severity, expected behaviour, and services are already on the ticket and are not shown. The id is Fraunces at 18px and the title is 15px, so the id is the loudest thing on the row.

Expected: The title is the primary text. Severity, expected behaviour, and services are visible on the row.

## T5. Status is one amber word

Severity: medium

Context: Open, Queued, Solving, and Verifying all use the same accent color. Fixed and completed go gray. Blocked and failed go salmon. The active row gets a slight tint, and every row lifts on hover, so the one being worked does not stay distinct.

Expected: Each status is distinguishable without reading the word alone. Hover does not fight the active row.

## T6. Row actions and the report look unfinished

Severity: medium

Context: Show report is a bare button with no pill style. Mark completed is a primary pill that only appears on verifying tickets. The report then opens as a 12px pre inside the card and pushes the list down.

Expected: Both actions use the existing button styles. The report opens in a panel that does not shove the list around.

## T7. Failure looks like the brand, and the run disappears

Severity: high

Context: Errors use the same amber as the status text. Several are still raw strings: workflow busy, resolve failed, request failed. A run that is still going only changes the button to Resolving… and a word on one row. Leave the page and that run disappears from the screen.

Expected: A failure is a sentence in an error color. The in-progress run shows which ticket is being handled. Coming back to the page still shows that run.
