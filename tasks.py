import os
import pathlib
import re

import jira
import yaml
from invoke import task

from utils import get_jira_pwd, print_bold

jira_username = None
jira_password = None
jira_cli = None

kHome = pathlib.Path.home()

kPackageDir = os.path.dirname(os.path.realpath(__file__))


def get_jira():
    global jira_cli
    if not jira_cli:
        jira_cli = jira.JIRA(
            options={'server': 'https://jira.mongodb.org'},
            basic_auth=(jira_username, jira_password),
        )

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
        c.run(f'git checkout {branch}')
        c.run(f'git fetch origin {branch}')
        c.run(f'git rebase origin/{branch}')
        c.run(f'git checkout -B server{ticket_number}', hide='both')

        issue = get_jira().issue(f'SERVER-{ticket_number}')
        if issue.fields.status.id == '1':  # '1' = Open
            print_bold('Transitioning Issue in Jira to "In Progress"')
            get_jira().transition_issue(issue, '4')  # '4' = Start Progress
        else:
            print_bold('Issue in Jira is not in "Open" status, not updating Jira')


@task(aliases='s')
def scons(c):
    """
    [unused at the moment] Wrapper around "python buildscripts/scons.py".
    """
    num_cpus = os.cpu_count()


@task(aliases='l', optional=['eslint'])
def lint(c, eslint=False):
    """
    Wrapper around clang_format and eslint.

    :param eslint: Run ESLint for JS files. Default: False.
    """
    with c.cd(str(kHome / 'mongo')):
        if eslint:
            c.run('python2 buildscripts/eslint.py fix')
        c.run('python2 buildscripts/clang_format.py format')


@task(aliases='c')
def commit(c):
    """
    Wrapper around git commit to automatically add changes and fill in the ticket number in the commit message.
    """

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
    print('review')


@task(aliases='p')
def patch(c):
    print('patch')


@task(aliases='u')
def self_update(c):
    with c.cd(kPackageDir):
        c.run('git fetch', warn=False)
        c.run('git rebase', warn=False)


@task(aliases='f', optional=['push'], post=[self_update])
def finalize(c, push=False):
    print('finalize')



