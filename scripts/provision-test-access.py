"""Provision the two Phase 5 test identities without printing bearer tokens.

Run explicitly against a private env file; writes new credentials to a separate
private handoff file. Existing tokens and grants are preserved. Restart required.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets


def provision(env_path, handoff_path):
    env_path, handoff_path = Path(env_path), Path(handoff_path)
    if handoff_path.exists():
        raise ValueError('Private handoff already exists; do not silently rotate distributed credentials.')
    lines = env_path.read_text(encoding='utf-8').splitlines()
    config = dict(line.split('=',1) for line in lines if '=' in line and not line.startswith('#'))
    keys = ('API_TOKENS_JSON','TEST_ADMIN_TOKENS_JSON','REVIEWER_GRANTS_JSON','TEST_SESSION_USERS_JSON')
    maps = {key:json.loads(config.get(key,'{}')) for key in keys}
    reviewer, admin = 'phase5-ungranted-reviewer', 'phase5-second-admin'
    if reviewer in maps['REVIEWER_GRANTS_JSON'] or admin in maps['TEST_SESSION_USERS_JSON']:
        raise ValueError('Phase 5 identities already exist; retrieve their private handoff rather than reprovisioning.')
    reviewer_token, admin_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    hashed = lambda token: 'sha256:'+hashlib.sha256(token.encode()).hexdigest()
    maps['API_TOKENS_JSON'][hashed(reviewer_token)] = reviewer
    maps['TEST_ADMIN_TOKENS_JSON'][hashed(admin_token)] = admin
    maps['REVIEWER_GRANTS_JSON'][reviewer] = []
    # Membership permits exercising a foreign-admin boundary without granting
    # the second admin ownership of the first admin's prepared namespaces.
    members = sorted({s for values in maps['TEST_SESSION_USERS_JSON'].values() for s in values} | {reviewer})
    for values in maps['TEST_SESSION_USERS_JSON'].values():
        if reviewer not in values: values.append(reviewer)
    maps['TEST_SESSION_USERS_JSON'][admin] = members
    output = [line for line in lines if line.split('=',1)[0] not in keys]
    output += [key+'='+json.dumps(value,separators=(',',':')) for key,value in maps.items()]
    # O_EXCL prevents overwriting an earlier handoff. Both files stay private;
    # on Windows also use a directory with restricted inherited ACLs.
    fd = os.open(handoff_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as private:
            json.dump({'reviewer-ungranted':reviewer_token,'test-admin-2':admin_token},private,indent=2)
        temporary = env_path.with_name(env_path.name+'.phase5-tmp')
        descriptor = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w',encoding='utf-8') as target:
            target.write('\n'.join(output)+'\n')
        os.replace(temporary,env_path)
    except Exception:
        # Never include the actual credentials in an exception or console log.
        raise RuntimeError('Provisioning failed. Inspect the private handoff and env paths before retrying.') from None


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--private-handoff',required=True)
    args=parser.parse_args()
    provision(args.env_file,args.private_handoff)
    print('Two test identities provisioned. Credentials are in the private handoff; restart the service to activate.')
