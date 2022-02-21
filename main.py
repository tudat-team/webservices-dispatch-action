import os
import json
import logging
import pprint
from github import Github
import pygit2
import re

LOGGER = logging.getLogger(__name__)

# set logging level to info
LOGGER.setLevel(logging.INFO)


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
    return pygit2_repo


def main():
    with open(os.environ["GITHUB_EVENT_PATH"], 'r') as fp:
        event_data = json.load(fp)
    event_name = os.environ['GITHUB_EVENT_NAME'].lower()

    LOGGER.info('github event: %s', event_name)
    LOGGER.info('github event data:\n%s', pprint.pformat(event_data))

    if event_name == 'repository_dispatch':
        client_payload = event_data['client_payload']
        LOGGER.info('repository_dispatch event')

        gh = Github(os.environ['GH_TOKEN'])

        # get repositories of project and respective feedstock
        project_repo = gh.get_repo(client_payload['repository'])
        feedstock_repo = gh.get_repo(client_payload['repository'] + "-feedstock")

        # check if repo exists
        if feedstock_repo is None:
            LOGGER.info(
                'repository_dispatch event: feedstock repository not found')
            return

        if client_payload["ref_type"] != "branch":
            LOGGER.info(
                'repository_dispatch event: only branch ref type supported'
            )
            return

        branch = client_payload["ref_name"]
        contents = project_repo.get_contents("version", ref=branch)
        version = contents.decoded_content.decode("ascii")

        # remap branch to subchannel
        subchannel = remap(client_payload["ref_name"])

        # clone feedstock and checkout template branch
        cloned_repo = clone_repo(
            feedstock_repo.clone_url,
            os.path.join(os.environ['GITHUB_WORKSPACE'], "feedstock"),
            'template',
            os.environ['GH_TOKEN'])

        previous_metadata = feedstock_repo.get_contents(
            "recipe/meta.yaml", ref=branch).decode("ascii")
        # use regex to get last version {% set version = "@VERSION@" %}
        previous_version = re.search(
            r'{%\s*set\s*version\s*=\s*"([^"]*)"\s*%}',
            previous_metadata).group(1)
        previous_build = re.search(
            r'{%\s*set\s*build\s*=\s*"([^"]*)"\s*%}',
            previous_metadata).group(1)
        previous_git_rev = re.search(
            r'{%\s*set\s*git_rev\s*=\s*"([^"]*)"\s*%}',
            previous_metadata).group(1)

        # if versions are the same, increment build
        if version == previous_version:
            new_build = int(previous_build) + 1
        else:
            new_build = 1

        vars = {
            "SUBCHANNEL": subchannel,
            "REPO_NAME": client_payload["repository"],
            "VERSION": version,
            "BUILD": new_build,
            "GIT_REV": client_payload["sha"],
        }

        # for each file, replace @VAR@ with values from dictionary
        for root, dirs, files in os.walk(
                os.path.join(os.environ['GITHUB_WORKSPACE'], "feedstock")):
            for file in files:
                with open(os.path.join(root, file), 'r') as f:
                    file_contents = f.read()

                for key, value in vars.items():
                    file_contents = file_contents.replace(
                        "@" + key + "@", value)

                with open(os.path.join(root, file), 'w') as f:
                    f.write(file_contents)

        user = "Delfi-C3"
        email = "Delfi-C3@users.noreply.github.com"

        # commit feedstock changes
        cloned_repo.index.add_all()
        cloned_repo.index.write()
        author = pygit2.Signature(user, email)
        commiter = pygit2.Signature(user, email)
        tree = cloned_repo.index.write_tree()
        pygit2_branch = cloned_repo.branches['origin/' + branch]
        pygit2_ref = cloned_repo.lookup_reference(pygit2_branch.name)
        oid = cloned_repo.create_commit(pygit2_ref, author, commiter,
                                        f"BOT: Automated feedstock update for sha:{client_payload['sha']} on {client_payload['repository']}",
                                        tree,
                                        [cloned_repo.head.get_object().hex])

        auth_method = 'x-access-token'
        credentials = pygit2.UserPass(auth_method, os.environ['GH_TOKEN'])
        callbacks = pygit2.RemoteCallbacks(
            credentials=credentials
        )
        remote = cloned_repo.remotes["origin"]
        remote.push([pygit2_ref], callbacks=callbacks)


def remap(key):
    key = {
        "develop": "dev",
        "master": "main",
        "main": "main",
    }
    if key in remap:
        return remap[key]
    return key


if __name__ == "__main__":
    main()
    # token = ''
    # github = Github(token)
    # repo = github.get_repo('tudat-team/tudat-resources-feedstock')
    # project_repo = github.get_repo('tudat-team/tudat-resources')
    # fil = project_repo.get_contents("version")
    # # print(fil.content)
    #
    # # repo = g.get_repo("PyGithub/PyGithub")
    #
    # branch = "develop"
    # contents = project_repo.get_contents("version", ref=branch)
    # version = contents.decoded_content.decode("ascii")

    # cloned_repo = clone_repo(repo..git_url, './tmp/feedstock', branch, token)

    # vars = {
    #     "REPOSITORY": "tudat-team/tudat-resources-feedstock",
    #
    #     "SUBCHANNEL": branch_channel_map(branch)
    # }

    # main()
