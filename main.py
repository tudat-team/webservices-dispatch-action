import os
import json
import logging
import pprint
from github import Github
import pygit2
import re
from util import *
import bumpversion.cli
from datetime import datetime, timedelta

LOGGER = logging.getLogger(__name__)

# set logging level to all
logging.basicConfig(level=logging.INFO)
# LOGGER.setLevel(logging.INFO)

BASE_REPO_URL = "https://{token}@github.com/{repository}.git"

import subprocess


def main():
    # two cases
    # 1. nightly changes detected from hub
    # 2. standard rerender
    # 3. push changes and initiate dev release

    if "TEST_DICT" in os.environ:
        event_data = json.loads(os.environ["TEST_DICT"])
    else:
        with open(os.environ["GITHUB_EVENT_PATH"], 'r') as fp:
            event_data = json.load(fp)

    # REPOSITORY = event_data["repository"]
    payload = event_data['client_payload']

    event_type = payload['event']
    event_name = os.environ['GITHUB_EVENT_NAME'].lower()

    LOGGER.info('github event: %s', event_name)
    LOGGER.info('github event data:\n%s', pprint.pformat(event_data))

    if event_name == 'repository_dispatch':

        gh = Github(os.environ['GH_TOKEN'])
        branch_name = payload['ref_name']

        s_repository = payload['repository']
        s_repository_feedstock = payload['repository'] + "-feedstock"
        repo = gh.get_repo(s_repository)
        feedstock_repo = gh.get_repo(s_repository_feedstock)

        # check if repo exists
        if not repository_exists(gh, s_repository_feedstock):
            LOGGER.error(
                'repository_dispatch event: feedstock repository not found')
            return

        if payload["ref_type"] != "branch":
            LOGGER.info(
                'repository_dispatch event: only branch ref type supported right now'
            )
            return

        if event_type == "push":
            sha = payload['sha']
            commit = repo.get_commit(sha=sha)
            message = commit.raw_data['commit']['message']
            tag = re.search(r'\[(.*?)\]', message)
            if tag:
                tag = tag.group(1)

                # remove match from message
                commit_message = message.replace(f'[{tag}]', '')
                commit_message = "[AUTO CI] 🤖 " + commit_message

                LOGGER.info('tag: %s', tag)
                if not tag.lower() == 'ci':
                    LOGGER.info('no ci tag detected')
                    return  # will stop main() entirely
                else:
                    rerender = True
                    release = True
            else:
                LOGGER.info('no ci tag detected')
                return  # will stop main() entirely

        # rerender
        elif event_type == "nightly":
            rerender = True
            # time 24 hours ago
            branch = repo.get_branch(branch_name)
            date_string = branch.commit.raw_data['commit']['author']['date']
            sha = branch.commit.raw_data['sha']
            since = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%SZ")
            # check if since is within 24 hrs
            if since > datetime.now() - timedelta(hours=24):
                LOGGER.info(
                    'since is within 24 hrs, nightly release will follow')
                release = True
                commit_message = "[BOT] Changes detected in project, nightly release 🌃 "
            else:
                return  # will stop main() entirely

        else:
            return  # (right now this is these are the only two events)

        if rerender:
            # right now we don't rerender here :( !!!!!
            # see https://github.com/tudat-team/.github/actions/workflows/autorerender.yml
            # LOGGER.info('cloning feedstock repository')
            # feedstock_repo, _ = clone_repo(
            #     repo_feedstock.clone_url,
            #     FEEDSTOCK_DIR,
            #     target_branch,
            #     os.environ['GH_TOKEN'])
            #
            # subprocess.run(["git", "checkout", target_branch], cwd=dir)
            pass

        if release:
            FEEDSTOCK_DIR = os.path.join(
                os.environ['GITHUB_WORKSPACE'],
                "feedstock")

            PROJECT_DIR = os.path.join(
                os.environ['GITHUB_WORKSPACE'],
                "project")

            LOGGER.info('cloning feedstock repository')
            feedstock_repo, _ = clone_repo(
                feedstock_repo.clone_url,
                FEEDSTOCK_DIR,
                branch_name,
                os.environ['GH_TOKEN'])

            LOGGER.info('cloning project repository')
            project_repo, _ = clone_repo(
                repo.clone_url,
                PROJECT_DIR,
                branch_name,
                os.environ['GH_TOKEN'])

            for repo, dir in [(s_repository_feedstock, FEEDSTOCK_DIR),
                              (s_repository, PROJECT_DIR)]:
                subprocess.run(["git", "checkout", branch_name], cwd=dir)

            # get version from version file in project repo open file
            with open(os.path.join(PROJECT_DIR, "version"), 'r') as fp:
                version = fp.read().rstrip("\n")

            # use regex to get last version {% set version = "@VERSION@" %}
            VERSION_REGEX = re.compile(
                r'{%\s*set\s*version\s*=\s*"([^"]*)"\s*%}')
            BUILD_REGEX = re.compile(r'{%\s*set\s*build\s*=\s*"([^"]*)"\s*%}')
            GIT_REV_REGEX = re.compile(
                r'{%\s*set\s*git_rev\s*=\s*"([^"]*)"\s*%}')
            VERSION_PEP440 = re.compile(
                r'(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(\.(?P<release>[a-z]+)(?P<dev>\d+))?')

            # match to pep440 and retrieve groups
            match = VERSION_PEP440.match(version)
            if match:
                major = match.group('major')
                minor = match.group('minor')
                patch = match.group('patch')
                release = match.group('release')
                dev = match.group('dev')
                if release:
                    version = f"{major}.{minor}.{patch}.{release}{dev}"
                else:
                    version = f"{major}.{minor}.{patch}"
                LOGGER.info('version: %s', version)
                LOGGER.info('major: %s', major)
                LOGGER.info('minor: %s', minor)
                LOGGER.info('patch: %s', patch)
                LOGGER.info('release: %s', release)
                LOGGER.info('dev: %s', dev)
            else:
                LOGGER.error(
                    'repository_dispatch event: could not parse version')
                return

            # retrieve values from previous feedstock metadata
            VAR_RETRIEVE = [
                ('version', 'recipe/meta.yaml', VERSION_REGEX),
                ('build', 'recipe/meta.yaml', BUILD_REGEX),
                ('git_rev', 'recipe/meta.yaml', GIT_REV_REGEX),
            ]

            old_var_vals = get_var_values(VAR_RETRIEVE, FEEDSTOCK_DIR)
            LOGGER.info('old_var_vals: %s', pprint.pformat(old_var_vals))
            LOGGER.info('version: %s', version)
            assert old_var_vals['version'] == version, "version mismatch"

            if branch_name == "develop":
                # print match information
                if release == "dev":
                    LOGGER.info(
                        'repository_dispatch event: bumping dev version')
                    # we bump the n of the dev release
                    bump_command = [
                        'dev']  # '--config-file', PROJECT_DIR + '/.bumpversion.cfg']
                else:
                    # we just increase patch, which will automatically start
                    # a dev release at the same time
                    LOGGER.info(
                        'repository_dispatch event: bumping patch version')
                    bump_command = [
                        'patch']  # '--config-file', PROJECT_DIR + '/.bumpversion.cfg']
            else:
                LOGGER.info(
                    'repository_dispatch event: only branch ref type supported'
                )
                return

            # set credentials
            user = "Delfi-C3"
            email = "Delfi-C3@users.noreply.github.com"
            subprocess.run(["git", "config", "--global", "user.name", user])
            subprocess.run(["git", "config", "--global", "user.email", email])

            # get current working directory
            cwd = os.getcwd()

            os.chdir(PROJECT_DIR)
            bumpversion.cli.main(bump_command)
            os.chdir(cwd)
            # bump version
            # print(bump_command)
            LOGGER.info('bumping version with command: %s', bump_command)

            # os.system(' '.join(bump_command))
            # subprocess.run(bump_command, cwd=PROJECT_DIR)
            # get version from version file in project repo open file
            with open(os.path.join(PROJECT_DIR, "version"), 'r') as fp:
                new_version = fp.read().rstrip("\n")

            new_var_vals = update_var_values(old_var_vals, new_version,
                                             payload['sha'])

            VAR_SUBSTITUTE = [
                # These note where/how to find the version numbers
                ('recipe/meta.yaml', VERSION_REGEX, r'{% set version = "{}" %}',
                 new_var_vals['version']),
                ('recipe/meta.yaml', BUILD_REGEX, r'{% set build = "{}" %}',
                 new_var_vals['build']),
                ('recipe/meta.yaml', GIT_REV_REGEX, r'{% set git_rev = "{}" %}',
                 new_var_vals['git_rev']),
            ]

            # substitute all vars accordingly
            for file, regex, subst, val in VAR_SUBSTITUTE:
                path = os.path.join(FEEDSTOCK_DIR, file)
                with open(path, 'r') as f:
                    s = f.read()
                    s = regex.sub(subst.replace("{}", str(val)), s)
                with open(path, 'w') as f:
                    f.write(s)

            # set credentials
            user = "Delfi-C3"
            email = "Delfi-C3@users.noreply.github.com"
            subprocess.run(["git", "config", "--global", "user.name", user])
            subprocess.run(["git", "config", "--global", "user.email", email])

            # checkout develop branch with subprocess
            for repo, dir in [(s_repository_feedstock, FEEDSTOCK_DIR),
                              (s_repository, PROJECT_DIR)]:
                # subprocess.run(["git", "checkout", "develop"], cwd=dir)

                # add all files
                subprocess.run(["git", "add", "."], cwd=dir)

                # use subprocess to commit, set cwd to target_repo
                subprocess.run(["git", "commit", "-m", commit_message],
                               cwd=dir)

                # # use subprocess to push
                repo_auth_url = BASE_REPO_URL.format(
                    token=os.environ["GH_TOKEN"],
                    repository=repo)

                subprocess.run(
                    ["git", "push", "--all", "-f", repo_auth_url], cwd=dir)


def remap(key):
    map = {
        "develop": "dev",
        "master": "main",
        "main": "main",
    }
    if key in map:
        return map[key]
    return key


import shutil

if __name__ == "__main__":
    main()
    # gh = Github('')
    # repo = gh.get_repo('tudat-team/tudat-resources')
    # target_branch = "develop"
    # #
    # # sha = '0952fd3f3d2a8350bb18f27a6a32351b45082336'
    # # commit = repo.get_commit(sha=sha)
    # # print(commit.raw_data['commit']['message'])
    #
    # # since = datetime.now() - timedelta(days=3)
    #
    # branch = repo.get_branch(target_branch)
    # date_string = branch.commit.raw_data['commit']['author']['date']
    # # convert to datetime
    # since = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%SZ")
    #
    # # check if since is within 24 hrs
    # if since > datetime.now() - timedelta(hours=24):
    #
    # print(branch)
    # print(branch.commit.raw_data['commit']['author']['date'])
    # print(branch.commit.raw_data)
    # print(branch.last_modified)
    # print(branch.commit.sha)

    # commits = repo.get_commits(since=since, branch='develop')
    # print(commits)
    # last = commits[0]

    # try:
    #     os.environ["GH_TOKEN"] = ""
    #     os.environ["GITHUB_WORKSPACE"] = "./tmp"
    #     os.environ["TEST_DICT"] = json.dumps(dict(
    #         client_payload=dict(
    #             ref_name="develop",
    #             repository="tudat-team/tudat-resources",
    #             sha="0952fd3f3d2a8350bb18f27a6a32351b45082336",
    #             ref="refs/heads/develop",
    #             ref_type="branch",
    #             actor="geoffreygarrett",
    #             event="push")
    #     ))
    #
    #     os.environ["GITHUB_EVENT_NAME"] = "repository_dispatch"
    #     main()
    #     shutil.rmtree(os.environ['GITHUB_WORKSPACE'])
    #
    # except ValueError as e:
    #     print(e)
    #     shutil.rmtree(os.environ['GITHUB_WORKSPACE'])

    # token = ''
    # github = Github(token)
    # g = Github(token)

    # if repository_exists(g, 'tudat-team/tudat-resources'):
    #     print("yes")
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
