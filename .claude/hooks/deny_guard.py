"""PreToolUse guard backing the deny list in settings.local.json.

Prefix-matched deny rules miss rewordings (cd prefixes, env vars, git -C, quoting,
chained or nested shells). This scans every command segment instead. It errs toward
blocking: a false positive costs one retry, a false negative can push or deploy.
"""
import json
import re
import sys

# Tokens after which the next word is still in command position.
WRAPPERS = {'env', 'sudo', 'command', 'exec', 'nohup', 'time', 'xargs', 'call', 'eval', 'iex',
            'invoke-expression', 'start-process', '-c', '-command', '/c', 'bash', 'sh', 'cmd',
            'powershell', 'pwsh'}
GIT_OPTS_WITH_VALUE = {'-c', '-C', '--git-dir', '--work-tree', '--namespace', '--config-env'}
ENV_FILE = re.compile(r'\.env\b.*')


def base(token):
    name = re.split(r'[\\/]', token)[-1].lower()
    return re.sub(r'\.(exe|cmd|bat)$', '', name)


def git_reason(args):
    i = 0
    while i < len(args) and args[i].startswith('-'):
        if args[i] in GIT_OPTS_WITH_VALUE:
            if i + 1 < len(args) and args[i + 1].lower().startswith('alias.'):
                return 'git aliases'
            i += 2
        else:
            i += 1
    if i >= len(args):
        return None
    sub, rest = args[i].lower(), args[i + 1:]
    if sub in ('push', 'checkout', 'switch', 'merge', 'rebase', 'reset') or re.search(r'[$%]', sub):
        return f'git {sub}'
    if sub == 'branch' and any(a.startswith('-') and a != '--show-current' for a in rest):
        return 'git branch with options'
    if sub == 'add' and any(a in ('.', './', '*', ':/', '--all') or re.fullmatch(r'-[a-zA-Z]*A[a-zA-Z]*', a)
                            for a in rest):
        return 'git add -A / git add .'
    if sub == 'config' and any(a.lower().startswith('alias.') for a in rest):
        return 'git aliases'
    return None


def reason(cmd):
    bare = re.sub(r'["\'`\\]', '', cmd)
    if re.search(r'deploy-aws|deploy-ec2|update-ec2', bare, re.I):
        return 'AWS/EC2 deploy scripts'
    if 'test_gate' in bare and '--update' in bare:
        return 'test_gate.py --update'
    # Backticks are an escape in PowerShell but command substitution in bash; try both.
    for text in (cmd.replace('`', ''), cmd.replace('`', ';'), cmd.replace('\\', '')):
        for seg in re.split(r'[;&|\n(){}]|\$\(', text):
            toks = re.sub(r'["\']', '', seg).split()
            names = [base(t) for t in toks]
            for i, name in enumerate(names):
                if ENV_FILE.fullmatch(name):
                    return 'reading .env files'
                if name == 'aws' and (i == 0 or names[i - 1] in WRAPPERS or '=' in toks[i - 1]):
                    return 'aws CLI'
                if name == 'git':
                    r = git_reason(toks[i + 1:])
                    if r:
                        return r
    return None


data = json.load(sys.stdin)
ti = data.get('tool_input', {})
if data.get('tool_name') in ('Bash', 'PowerShell'):
    r = reason(ti.get('command', ''))
else:
    r = 'reading .env files' if any(ENV_FILE.fullmatch(base(str(ti.get(k, ''))))
                                    for k in ('file_path', 'path', 'glob')) else None
if r:
    print(f'Blocked by .claude/hooks/deny_guard.py: {r}', file=sys.stderr)
    sys.exit(2)
