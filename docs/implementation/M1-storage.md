# M1 - Storage Layer

## Objective

Implement persistent structured storage and raw-evidence storage behind
interfaces.

## Read before starting

-   M0 specification and completed code
-   `docs/design-docs/data-dictionary-v1.md`
-   `docs/design-docs/system-architecture-v1.md`

## Implement

-   Turso repository/schema for structured entities.
-   Cloudflare R2 adapter for production raw evidence.
-   Local filesystem raw-evidence adapter for development.
-   Immutable raw-object naming/versioning using company, source,
    retrieval timestamp and checksum.
-   Schema/migration mechanism.
-   Bidirectional provenance identifiers.
-   Integration tests using safe local/test configuration.

## Rules

-   Do not store raw PDFs/iXBRL/large JSON blobs in Turso.
-   Do not overwrite logical raw retrieval events.
-   Secrets must come from environment/secrets configuration.
-   Cloud-specific code stays behind interfaces.

## Acceptance criteria

-   Save/retrieve Company, Source, Document and Fact metadata.
-   Store/retrieve a raw object through the storage interface.
-   Link a structured fact to source/document/raw object metadata.
-   No credentials committed.
