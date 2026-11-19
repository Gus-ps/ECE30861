"""Text checks on infrastructure/aws.yaml for D11/D12 (PyYAML isn't a dependency)."""
from pathlib import Path
import re
import unittest

TEMPLATE = (Path(__file__).resolve().parents[1] / 'infrastructure' / 'aws.yaml').read_text()


def block(name):
    """The lines of one top-level resource or output, up to the next sibling key."""
    return re.search(rf'^  {name}:\n((?:    .*\n|\s*\n)*)', TEMPLATE, re.M).group(1)


class TemplateTests(unittest.TestCase):
    def test_deletion_ledger_bucket(self):
        bucket = block('DeletionLedgerBucket')
        for line in ('Type: AWS::S3::Bucket', 'DeletionPolicy: Retain', 'UpdateReplacePolicy: Retain',
                     'Status: Enabled', 'BlockPublicAcls: true', 'BlockPublicPolicy: true',
                     'IgnorePublicAcls: true', 'RestrictPublicBuckets: true', 'SSEAlgorithm: AES256'):
            self.assertIn(line, bucket)
        self.assertNotIn('ObjectLock', bucket)
        self.assertNotIn('LifecycleConfiguration', bucket)
        self.assertIn('Value: !Ref DeletionLedgerBucket', block('DeletionLedgerBucketName'))

    def test_container_receives_the_bucket(self):
        self.assertIn('- Name: DELETION_LEDGER_BUCKET\n            Value: !Ref DeletionLedgerBucket',
                      block('Service'))
        self.assertNotIn('DELETION_LEDGER_PATH', TEMPLATE)

    def test_task_role_may_only_put_and_list_ledger_keys(self):
        role = block('TaskRole')
        self.assertEqual(re.findall(r's3:\w+', role), ['s3:PutObject', 's3:ListBucket', 's3:prefix'])
        self.assertIn("Resource: !Sub '${DeletionLedgerBucket.Arn}/deletions/*'", role)
        self.assertIn('s3:prefix: deletions/*', role)
        self.assertNotIn('s3:DeleteObject', TEMPLATE)

    def test_database_keeps_no_snapshot_beyond_one_day_backups(self):
        database = block('Database')
        for line in ('DeletionPolicy: Delete', 'UpdateReplacePolicy: Delete', 'BackupRetentionPeriod: 1'):
            self.assertIn(line, database)
        self.assertNotIn('Snapshot\n', database)


if __name__ == '__main__':
    unittest.main()
