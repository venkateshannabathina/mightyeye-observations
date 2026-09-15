# Architecture handoff

## Completed at this stage

1. DeepStream producer converts metadata into the public Observation.
2. Fake producer emits the same contract for development without a camera.
3. Files persist that exact JSON for validation and replay.
4. World State accepts only the public contract and maintains the latest local camera tracks.
5. Minimal event logic demonstrates line-crossing and zone-entry candidates referencing the supporting observation.

No DeepStream import is permitted in contracts, file readers, fake producers, or consumers. A source import check runs in CI. Keep future vendor-specific integrations inside their own producer modules and expose only the public contract.

## Next components

- **World State production service:** expiry, durable checkpoints, track lifecycle, time ordering.
- **Cross-camera + event engine:** candidate association with uncertainty and configurable event policies. Never merge equal local tracker IDs across cameras.
- **Candidate incident:** aggregate supporting observations and rule rationale.
- **Optional VLM:** verify evidence when available; preserve uncertainty.
- **Incident:** explicit status transitions and human review.
- **Database + evidence:** durable observations, incident revisions, retention and resolvable media references.
- **Dashboard:** consume incident APIs and evidence; no SDK metadata.

The reference consumer is a handoff example, not a complete incident engine. The sibling older MightyEye prototype has a nested frame-based Observation with additional required provenance fields. Integration needs an explicit migration and provenance decisions; these fields must not be fabricated from this 12-field format. Keep the new public contract at the ingestion boundary when performing that migration.
