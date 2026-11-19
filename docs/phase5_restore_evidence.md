# Phase 5 hosted restore evidence (DEL-11)

Assertions: `P5-DELETE-RESTORE`, `P5-MANUAL-DELETE-BACKUPS`. A person carries this out on
AWS after deploying the DEL-9 template (`infrastructure/aws.yaml`). The restore steps
follow D12, as written in `docs/phase5_security.md` ("Restore on ECS/RDS").

## Checklist

1. Deploy the stack and note the commit SHA and the `DeletionLedgerBucketName` output.
2. Upload two workbooks as the same owner: A (to delete) and B (to keep). Note both IDs.
3. Note the UTC time, then wait at least 5 minutes so a point-in-time restore before the
   deletion is possible.
4. `DELETE /api/v1/workbooks/{A}` returns 204.
5. In the bucket, `deletions/{A}.json` exists and holds only `workbook_id` and
   `timestamp`.
6. Stop traffic (scale the service to 0 or pause it).
7. Restore the database to a new instance at the time from step 3.
8. Point `DB_HOST` at the new instance; leave the bucket untouched.
9. Start one task. Its logs show no ledger error and it reaches healthy.
10. `GET /api/v1/workbooks/{A}/history` returns 404; the same request for B returns 200.
11. Scale back up, then delete the old instance and any manual snapshot.
12. Optional: set both `DELETION_LEDGER_PATH` and `DELETION_LEDGER_BUCKET` on a test task
    and confirm it refuses to start with the D11 message.

## Results

| Step | Expected | Observed | Pass/Fail | Time (UTC) | Evidence (log, screenshot) |
| --- | --- | --- | --- | --- | --- |
| 1 | Stack deployed, bucket name noted | | | | |
| 4 | 204 for A | | | | |
| 5 | `deletions/{A}.json` with two fields | | | | |
| 7 | Restored instance available | | | | |
| 9 | Healthy task, no ledger error | | | | |
| 10 | A 404, B 200 | | | | |
| 11 | Old instance and manual snapshot removed | | | | |
| 12 | Startup refused (optional) | | | | |

Commit SHA: \
Performed by: \
Date: \
Notes:
