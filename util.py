import os
import requests
import urllib3.util.retry
import pygit2
from github import Github


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
    return pygit2_repo, pygit2_ref


# class BumpType(enum.Enum):
#     major = 1
#     minor = 2
#     patch = 3
#     pre = 4
#     build = 5


def get_var_values(var_retrieve, root=''):
    ret = {}
    for var, file, regex in var_retrieve:
        with open(os.path.join(root, file), 'r') as f:
            s = f.read()
            m = regex.search(s)
            print(regex, var)
            v = m.group(1)
            ret[var] = v

            # LOGGING.debug('%s: %s', var, v)
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


# TODO
# Remove repository_exists, replace by load_repository(github_client, repo_name) and throw/log error if not exists