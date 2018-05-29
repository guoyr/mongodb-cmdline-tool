import os
import pathlib
import re
import sys

import jira
import yaml
from invoke import task

from utils import get_jira_pwd, print_bold

jira_username = None
jira_password = None
jira_cli = None

kHome = pathlib.Path.home()

kPackageDir = pathlib.Path(os.path.dirname(os.path.realpath(__file__)))


def get_jira():
    global jira_cli
    if not jira_cli:
        try:
            jira_cli = jira.JIRA(
                options={'server': 'https://jira.mongodb.org'},
                basic_auth=(jira_username, jira_password),
                validate=True,
            )
        except jira.exceptions.JIRAError as e:
            if e.status_code == '403' or e.status_code == 403:
                print('CAPTCHA required, please log out and log back into Jira')
                return None

    return jira_cli


def init(c):
    global jira_username
    global jira_password

    if jira_username:
        return

    # Use the Evergreen username for Jira as well.
    with open(pathlib.Path.home() / '.evergreen.yml') as evg_file:
        evg_config = yaml.load(evg_file)
        jira_username = evg_config['user']
    jira_password = get_jira_pwd()


def _strip_proj(ticket_number):
    match = re.search(r'[0-9]+', ticket_number)
    if not match:
        raise ValueError(f'{ticket_number} is not a valid ticket number')
    return match.group(0)


def _get_ticket_numbers(c):
    """Get the ticket numbers from the commit and the branch."""
    branch = c.run('git rev-parse --abbrev-ref HEAD', hide='both').stdout
    ticket_number = _strip_proj(branch)
    commit_msg = c.run('git log --oneline -1 --pretty=%s', hide='both').stdout
    commit_ticket_number = _strip_proj(commit_msg)
    return commit_ticket_number, ticket_number


def _load_cache(c):
    try:
        with open(str(kPackageDir / 'cache'), 'r') as cache_file:
            cache = yaml.load(cache_file)
            return cache or {}
    except IOError:
        # File doesn't exist.
        return {}


def _store_cache(c, cache_dict):
    with open(str(kPackageDir / 'cache'), 'w') as cache_file:
        yaml.dump(cache_dict, cache_file)

def _git_refresh(c, branch):
    old_branch = c.run('git rev-parse --abbrev-ref HEAD', hide='both').stdout
    c.run(f'git checkout {branch}')
    c.run(f'git fetch origin {branch}')
    c.run(f'git rebase origin/{branch}')
    c.run(f'git checkout {old_branch}')

@task(aliases='n', positional=['ticket_number'], optional=['branch'])
def new(c, ticket_number, branch='master'):
    """
    Create or switch to the branch for a ticket.

    :param ticket_number: Digits of the Jira ticket.
    :param branch: Base branch for this ticket. Default: master.
    """
    init(c)
    ticket_number = _strip_proj(ticket_number)

    res = c.run(f'git rev-parse --verify server{ticket_number}', warn=True, hide=True)
    if res.return_code == 0:
        print_bold(f'Checking out existing branch: server{ticket_number}')
        c.run(f'git checkout server{ticket_number}')
    else:
        print_bold(f'Updating {branch} to latest and creating new branch: server{ticket_number}')
        _git_refresh(c, branch)
        c.run(f'git checkout -B server{ticket_number}', hide='both')

        jirac = get_jira()
        if jirac:
            issue = jirac.issue(f'SERVER-{ticket_number}')
            if issue.fields.status.id == '1':  # '1' = Open
                print_bold('Transitioning Issue in Jira to "In Progress"')
                jirac.transition_issue(issue, '4')  # '4' = Start Progress
            else:
                print_bold('Issue in Jira is not in "Open" status, not updating Jira')


@task(aliases='s')
def scons(c):
    """
    [unused at the moment] Wrapper around "python buildscripts/scons.py".
    """
    init(c)
    num_cpus = os.cpu_count()


@task(aliases='l', optional=['eslint'])
def lint(c, eslint=False):
    """
    Wrapper around clang_format and eslint.

    :param eslint: Run ESLint for JS files. Default: False.
    """
    init()
    with c.cd(str(kHome / 'mongo')):
        if eslint:
            c.run('python2 buildscripts/eslint.py fix')
        c.run('python2 buildscripts/clang_format.py format')


@task(aliases='c')
def commit(c):
    """
    Wrapper around git commit to automatically add changes and fill in the ticket number in the commit message.
    """
    init(c)
    c.run('git add -u')
    c.run('git add src/')
    c.run('git add jstests/')

    commit_num, branch_num = _get_ticket_numbers(c)

    if commit_num == branch_num:
        c.run('git commit --amend --no-edit')
    else:
        raw_commit_msg = input('Please enter the commit message (without ticket number): ')
        c.run(f'git commit -m "SERVER-{commit_num} {raw_commit_msg}"')

    print_bold('Committed local changes')


@task(aliases='r', optional=['new_cr'])
def review(c, new_cr=False):
    init(c)
    commit_num, branch_num = _get_ticket_numbers(c)
    if commit_num != branch_num:
        raise ValueError('Please commit your changes before submitting them for review.')

    cache = _load_cache(c)
    if commit_num in cache and 'cr' in cache[commit_num]:
        issue_number = cache[commit_num]['cr']
    else:
        cache[commit_num] = {}
        issue_number = None

    commit_msg = c.run('git log --oneline -1 --pretty=%s', hide='both').stdout.strip()
    cmd = f'python2 {kPackageDir / "upload.py"} --rev HEAD~1 --nojira -y ' \
          f'--git_similarity 90 --check-clang-format --check-eslint'
    if issue_number and not new_cr:
        cmd += f' -i {issue_number}'
    else:
        # New issue, add title.
        cmd += f' -t "{commit_msg}"'

    res = c.run(cmd)

    match = re.search('Issue created. URL: (.*)', res.stdout)
    if match:
        url = match.group(1)
        issue_number = url.split('/')[-1]
        jirac = get_jira()
        if jirac:
            ticket = get_jira().issue(f'SERVER-{commit_num}')
            get_jira().add_comment(
                ticket,
                f'CR: {url}',
                visibility={'type': 'role', 'value': 'Developers'}
            )

    if not issue_number:
        raise ValueError('Something went wrong, no CR issue number was found')

    cache[commit_num]['cr'] = issue_number

    _store_cache(c, cache)


@task(aliases='p', optional=['branch', 'finalize'])
def patch(c, branch='master', finalize=True):
    """
    Run patch build in Evergreen.

    :return:
    """
    init(c)
    temp_branch = 'patch-build-branch'
    feature_branch = c.run('git rev-parse --abbrev-ref HEAD', hide='both').stdout
    commit_msg = c.run('git log --oneline -1 --pretty=%s', hide='both').stdout.strip()

    commit_num, branch_num = _get_ticket_numbers(c)
    if commit_num != branch_num:
        raise ValueError('Please commit your changes before putting up a patch build.')

    try:
        _git_refresh(c, branch)

        c.run(f'git checkout -B {temp_branch}')
        res = c.run(f'git rebase {branch}', warn=True)
        if res.return_code != 0:
            print(f'[WARNING] {feature_branch} did not rebase cleanly. Please manually run '
                  f'"git rebase {branch}" and retry the patch build again')
            c.run('git rebase --abort')
        else:
            cmd = f'evergreen patch -y -d "{commit_msg}"'
            if finalize:
                cmd += ' -f'
            c.run(cmd)

            # TODO: add comment to Jira.
    finally:
        c.run(f'git checkout {feature_branch}')


@task(aliases='u')
def self_update(c):
    with c.cd(str(kPackageDir)):
        c.run('git fetch', warn=False)
        c.run('git rebase', warn=False)


@task(aliases='f', optional=['push', 'branch'], post=[self_update])
def finalize(c, push=False, branch='master'):
    init(c)

    commit_num, branch_num = _get_ticket_numbers(c)
    if commit_num != branch_num:
        raise ValueError('Please commit your changes before putting up a patch build.')

    _git_refresh(c, branch)
    c.run('git pull --rebase mongo master')
