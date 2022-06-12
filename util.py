import os
import requests
import urllib3.util.retry
import logging
import subprocess
import re
import pprint
from datetime import datetime, timedelta
import pygit2
from github import Github
from github.GithubException import UnknownObjectException


# Create logger with logging level set to all
LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def get_project_and_feedstock_repos(github_client, repo_name):
    """
    Get the project and feedstock repos from the repo name.
    Parameters
    ----------
    github_client : github.MainClass.Github
        The Github client.
    repo_name : str
        The repo name.
    Returns
    -------
    project_repo : github.Repository.Repository
        The project repository.
    feedstock_repo : github.Repository.Repository
        The feedstock repository.
    feedstock_repo_name : str
        The feedstock repository name.
    """
    feedstock_repo_name = repo_name + "-feedstock"
    project_repo = github_client.get_repo(repo_name)

    # Get feedstock repository
    try:
        feedstock_repo = github_client.get_repo(feedstock_repo_name)
    # If feedstock repo does not exist, log an error and exit
    except UnknownObjectException:
        LOGGER.error(
            "repository_dispatch event: feedstock repository of '%s' not found" % repo_name)
        return None, None, None

    return project_repo, feedstock_repo, feedstock_repo_name

def get_project_version(repo_dir, VERSION_PEP440=re.compile(r'(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(\.(?P<release>[a-z]+)(?P<dev>\d+))?')):
    """
    Get the project version from the version file in a given repository.
    Parameters
    ----------
    repo_dir : str
        The path to the repo directory.
    VERSION_PEP440 : re.compile
        The regex to match the version.
    Returns
    -------
    str
        The project version.
    """
    # Get version from version file in project repo
    with open(os.path.join(repo_dir, "version"), 'r') as fp:
        version = fp.read().rstrip("\n")

    # Match version from file to pep440 and retrieve groups
    match = VERSION_PEP440.match(version)
    if match:
        major = match.group("major")
        minor = match.group("minor")
        patch = match.group("patch")
        release = match.group("release")
        dev = match.group("dev")
        if release:
            version = f"{major}.{minor}.{patch}.{release}{dev}"
        else:
            version = f"{major}.{minor}.{patch}"
        LOGGER.info("version: %s", version)
        LOGGER.info("major: %s", major)
        LOGGER.info("minor: %s", minor)
        LOGGER.info("patch: %s", patch)
        LOGGER.info("release: %s", release)
        LOGGER.info("dev: %s", dev)
        return version
    else:
        LOGGER.error(
            "repository_dispatch event: could not parse version")
        return None

def get_commit_tags(repo, commit_hash, supported_tags=["ci", "rerender"]):
    """
    Get the tags of a commit.
    Parameters
    ----------
    repo : github.Repository.Repository
        The repository.
    commit_hash : str
        The commit hash.
    supported_tags : list[str]
        List of tags that are to be searched for.
    Returns
    -------
    tags : dict[str, bool]
        Dictionary of tags found, with supported tags as keys and the value denoting wether they were found.
    commit_message : str
        New commit message cleaned of the tag in brackets, but with the tag in front instead.
    """
    # Get commit from its sha
    commit = repo.get_commit(sha=commit_hash)
    message = commit.raw_data["commit"]["message"]

    # Extract commit tag if there is one
    tag = re.search(r'\[(.*?)\]', message)
    if tag:
        tag = tag.group(1)
        LOGGER.info("tag: %s", tag)

        if tag.lower() in supported_tags:
            # Remove tag from message, and add it in front
            commit_message = message.replace(f'[{tag}]', "")
            # Clean excess spaces
            commit_message = re.sub(r'\s+', " ", commit_message).strip()
            # Add tag in front of commit message
            commit_message = "%s: %s" % (tag.upper(), commit_message)

            # Return True for the tag that was found
            return {possible_tag: tag.lower() == possible_tag for possible_tag in supported_tags}, commit_message
        else:
            # Quit if the tag is not in the list of supported ones
            LOGGER.info(
                "no supported tag detected (was '%s', supported are %s" % (tag, supported_tags)
            )
            return {possible_tag: False for possible_tag in supported_tags}, None
    else:
        # Quit if there is not tag
        LOGGER.info("no tag detected")
        return {possible_tag: False for possible_tag in supported_tags}, None

def was_branch_last_commit_recent(repo, branch_name, time_treshold=timedelta(hours=24)):
    """
    Check if the last commit of a branch is recent.
    Parameters
    ----------
    repo : github.Repository.Repository
        The repository.
    branch_name : str
        The branch name.
    time_treshold : datetime.timedelta
        The time threshold under which the last commit will be considered recent.
    Returns
    -------
    bool
        True if the last commit is recent, False otherwise.
    """
    # Get info of latest commit for given branch
    branch = repo.get_branch(branch_name)
    date_string = branch.commit.raw_data["commit"]["author"]["date"]
    last_commit_time = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%SZ")
    
    # Trigger release if last commit time was less than some time ago
    if last_commit_time > datetime.now() - time_treshold:
        LOGGER.info(
            "since is within specified time, nightly release will follow")
        return True
    return False

def push_all_to_github(repo, branch_name, directory, commit_message):
    """
    Push all files in a directory to a github repository.
    Parameters
    ----------
    repo : github.Repository.Repository
        The repository.
    branch_name : str
        The branch name.
    directory : str
        The directory to push.
    commit_message : str
        The commit message.
    """
    # Add all files
    subprocess.run(["git", "add", "."], cwd=directory)

    # Commit with proper commit message
    subprocess.run(["git", "commit", "-m", commit_message], cwd=directory)

    # Get url to push to
    repo_auth_url = "https://%s@github.com/%s.git" % (os.environ["GH_TOKEN"], repo)

    # Push changes and tags
    subprocess.run(["git", "push", "--all", "-f", repo_auth_url], cwd=directory)
    subprocess.run(["git", "push", repo_auth_url, branch_name, "--tags"], cwd=directory)

def create_api_sessions(github_token):
    """Create API sessions for GitHub.
    Parameters
    ----------
    github_token : str
        The GitHub access token.
    Returns
    -------
    session : requests.Session
        A `requests` session w/ the beta `check_run` API configured.
    gh : github.MainClass.Github
        A `Github` object from the PyGithub package.
    """
    # based on
    #  https://alexwlchan.net/2019/03/
    #    creating-a-github-action-to-auto-merge-pull-requests/
    # with lots of edits
    sess = requests.Session()
    sess.headers = {
        "Accept": "; ".join([
            "application/vnd.github.v3+json",
            # special beta api for check_suites endpoint
            "application/vnd.github.antiope-preview+json",
        ]),
        "Authorization": f"token {github_token}",
        "User-Agent": f"GitHub Actions script in {__file__}"
    }

    def raise_for_status(resp, *args, **kwargs):
        try:
            resp.raise_for_status()
        except Exception as e:
            print('ERROR:', resp.text)
            raise e

    sess.hooks["response"].append(raise_for_status)

    # build a github object too
    gh = Github(
        github_token,
        retry=urllib3.util.retry.Retry(total=10, backoff_factor=0.1))

    return sess, gh

def clone_repo(clone_url, clone_path, branch, auth_token):
    # Use pygit2 to clone the repo to disk
    # if using github app pem key token, use x-access-token like below
    # if you were using a personal access token, use auth_method = 'x-oauth-basic' AND reverse the auth_method and token parameters
    auth_method = 'x-access-token'
    callbacks = pygit2.RemoteCallbacks(pygit2.UserPass(auth_method, auth_token))
    pygit2_repo = pygit2.clone_repository(clone_url, clone_path,
                                          callbacks=callbacks)
    pygit2_branch = pygit2_repo.branches['origin/' + branch]
    pygit2_ref = pygit2_repo.lookup_reference(pygit2_branch.name)
    pygit2_repo.checkout(pygit2_ref)
    # Checkout correct branch
    subprocess.run(["git", "checkout", branch], cwd=clone_path)
    return pygit2_repo, pygit2_ref

def get_var_values(var_retrieve, root=''):
    ret = {}
    for var, file, regex in var_retrieve:
        with open(os.path.join(root, file), 'r') as f:
            s = f.read()
            m = regex.search(s)
            v = m.group(1)
            ret[var] = v
    return ret


def update_var_values(var_retrieved, version_tag, git_rev=None, root=''):
    ret = {}
    git_rev = version_tag if git_rev is None else git_rev
    for k, v in var_retrieved.items():
        if k == 'build':
            if var_retrieved['version'] == version_tag:
                # NOTE(Geoffrey): we are only bumping build number at the moment.
                v = int(v) + 1
            else:
                v = 0
        elif k == 'git_rev':
            v = git_rev
        elif k == 'version':
            v = version_tag
        ret[k] = v
    return ret