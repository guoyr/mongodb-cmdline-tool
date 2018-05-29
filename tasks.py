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

cwd = os.getcwd()


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


def strip_proj(ticket_number):
    match = re.search(r'[0-9]+', ticket_number)
    if not match:
        raise ValueError(f'{ticket_number} is not a valid ticket number')
    return match.group(0)


@task(aliases='n', positional=['ticket_number'], optional=['branch'])
def new(c, ticket_number, branch='master'):
    """
    Create or switch to the branch for a ticket.

    :param ticket_number: Digits of the Jira ticket.
    :param branch: Base branch for this ticket, defaults to "master".
    """
    init(c)
    ticket_number = strip_proj(ticket_number)

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
    # TODO
    num_cpus = os.cpu_count()


@task(aliases='c', optional=['fixup'])
def commit(c, fixup=True):
    """
    Wrapper around git commit to automatically add changes and fill in the ticket number in the commit message.

    :param fixup: Whether to squash uncommitted changes into the latest commit.
    """
    branch = c.run('git rev-parse --abbrev-ref HEAD', hide=True).stdout
    ticket_number = strip_proj(branch)
    c.run('git add -u')
    if fixup:
        commit_msg = c.run('git log --oneline -1 --pretty=%s', ).stdout
        commit_ticket = strip_proj(commit_msg)
        if commit_ticket == ticket_number:
            c.run('git commit --amend --no-edit')
    raw_commit_msg = input('Please enter the commit message (without ticket number): ')
    c.run(f'git commit -m "SERVER-{ticket_number} {raw_commit_msg}"')
    print_bold('Committed local changes')


@task(aliases='r', optional=['new_cr'])
def review(c, new_cr=False):
    print('review')


@task(aliases='p')
def patch(c):
    print('patch')


@task(aliases='u')
def self_update(c):
    with c.cd(os.path.dirname(os.path.realpath(__file__))):
        c.run('git pull --rebase', warn=False)


@task(aliases='f', optional=['push'], post=[self_update])
def finalize(c, push=False):
    print('finalize')



