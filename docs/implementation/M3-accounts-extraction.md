# M3 - Accounts Acquisition and Financial Extraction

## Objective

Acquire filed accounts and produce canonical financial facts for the MVP
risk variables.

## Source priority

1.  Companies House iXBRL/XHTML
2.  Native PDF deterministic extraction
3.  OCR deterministic extraction when necessary
4.  LLM-assisted candidate extraction only when necessary

## Required canonical concepts

CURRENT_ASSETS, CURRENT_LIABILITIES, INVENTORY, NET_ASSETS,
TOTAL_ASSETS, INTEREST_BEARING_DEBT.

## Supporting concepts

FIXED_ASSETS, CASH, DEBTORS, TOTAL_LIABILITIES, BANK_LOANS, OTHER_LOANS,
INVOICE_FINANCING, OTHER_INTEREST_BEARING_BORROWINGS.

## Implement

-   Filing-to-document discovery.
-   Document acquisition and raw R2/local persistence.
-   iXBRL deterministic parser and concept mapping.
-   PDF fallback path.
-   Period, unit, currency and evidence locators.
-   Composite interest-bearing-debt construction with component
    provenance.
-   Comparable-period metadata.

## Rules

-   Do not assume an absent inventory/debt line equals zero.
-   Preserve source concept as well as canonical concept.
-   Keep candidate values when validation later needs to resolve
    conflicts.

## Acceptance criteria

-   Core facts can be extracted or fail with explicit status.
-   Every fact links to evidence location and raw document.
-   Three reference companies are supported without fabricated values.
