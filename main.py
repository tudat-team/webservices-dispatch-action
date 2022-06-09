import os
import json
import logging
import pprint
from github import Github
import re
from util import *
import bumpversion.cli
from datetime import datetime, timedelta
import subprocess


# Create logger with logging level set to all
LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main():
    # Two events:
    # 1. Push -> look for tags in commit message and rerender and/or release if found
    # 2. Nightly -> rerender and release if last changes were more than 24hrs ago

    # Load event data from test dictionary or from GitHub even path environment variable
    if "TEST_DICT" in os.environ:
        event_data = json.loads(os.environ["TEST_DICT"])
    else:
        with open(os.environ["GITHUB_EVENT_PATH"], "r") as fp:
            event_data = json.load(fp)

    # Extract payload and event info from event data
    payload = event_data["client_payload"]
    event_type = payload["event"]
    event_name = os.environ["GITHUB_EVENT_NAME"].lower()
    LOGGER.info("github event: %s", event_name)
    LOGGER.info("github event data:\n%s", pprint.pformat(event_data))
    
    # Quit if the event is not a repository dispatch
    if event_name != "repository_dispatch":
        return

    # Quit if the ref type is not a branch
    if payload["ref_type"] != "branch":
        LOGGER.info(
            "repository_dispatch event: only branch ref type supported right now (was '%s')" % payload["ref_type"]
        )
        return

    # Start GitHub client
    gh = Github(os.environ['GH_TOKEN'])

    # Get repository
    branch_name = payload["ref_name"]
    s_repository = payload["repository"]

    project_repo, feedstock_repo, s_repository_feedstock = get_project_and_feedstock_repos(gh, s_repository)
    if project_repo is None:
        return

    # If the even is a push, analyze it to search for [CI] tag
    if event_type == "push":
        # Get possible tags in commit message, as well as new commit message for push after rerender or release
        tags_found, commit_message = get_commit_tags(project_repo, payload["sha"])
        rerender = tags_found["rerender"] or tags_found["ci"]
        release = tags_found["ci"]
        # Quit if no tags were found
        if not rerender and not release:
            return

    # If the even is a nightly, rerender, check if there was changes in the last 24hrs and if so, release
    elif event_type == "nightly":
        # Trigger rerender
        rerender = True
        # If last commit was less than 22hrs ago, trigger release
        release = was_last_branch_commit_recent(project_repo, branch_name, time_treshold=timedelta(hours=22))

    # Quit if the event is not a push nor a nightly
    else:
        return

    # Rerender the feedstock
    if rerender:
        # right now we don't rerender here (。_。) !!!!!
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

    # Release a conda package
    if release:
        # Create path for feedstock and project repos locally
        FEEDSTOCK_DIR, PROJECT_DIR = [os.path.join(os.environ["GITHUB_WORKSPACE"], name) for name in ["feedstock", "project"]]

        # Clone the feedstock and project repos
        LOGGER.info("cloning feedstock repository")
        clone_repo(feedstock_repo.clone_url, FEEDSTOCK_DIR, branch_name, os.environ['GH_TOKEN'])
        LOGGER.info('cloning project repository')
        clone_repo(project_repo.clone_url, PROJECT_DIR, branch_name, os.environ['GH_TOKEN'])

        # Checkout correct repo branch
        for dir in [FEEDSTOCK_DIR, PROJECT_DIR]:
            subprocess.run(["git", "checkout", branch_name], cwd=dir)

        # Get version from version file in project repo
        with open(os.path.join(PROJECT_DIR, "version"), 'r') as fp:
            version = fp.read().rstrip("\n")

        # Declare regex to get last version {% set version = "@VERSION@" %}
        VERSION_REGEX = re.compile(r'{%\s*set\s*version\s*=\s*"([^"]*)"\s*%}')
        BUILD_REGEX = re.compile(r'{%\s*set\s*build\s*=\s*"([^"]*)"\s*%}')
        GIT_REV_REGEX = re.compile(r'{%\s*set\s*git_rev\s*=\s*"([^"]*)"\s*%}')
        VERSION_PEP440 = re.compile(r'(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(\.(?P<release>[a-z]+)(?P<dev>\d+))?')
        TARGETS_REGEX = re.compile(r"-\s+\[(?P<channel>[\w,-].+)\, \s+(?P<subchannel>[\w,-]+)]")
        TARGETS2_REGEX = re.compile(r"(?<=channel_targets:\n\s\s)-\s+(?P<targets>[\s,\w,-]+)")

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
        else:
            LOGGER.error(
                "repository_dispatch event: could not parse version")
            return

        # Retrieve version, build, and rev values from previous feedstock metadata
        VAR_RETRIEVE = [
            ("version", "recipe/meta.yaml", VERSION_REGEX),
            ("build", "recipe/meta.yaml", BUILD_REGEX),
            ("git_rev", "recipe/meta.yaml", GIT_REV_REGEX),
        ]
        old_var_vals = get_var_values(VAR_RETRIEVE, FEEDSTOCK_DIR)
        LOGGER.info("old_var_vals: %s", pprint.pformat(old_var_vals))
        LOGGER.info("version: %s", version)
        # Make sure the version is the same as the one in the feedstock
        assert old_var_vals["version"] == version, "version mismatch"

        # Trigger release if branch is develop, or if the environment is test
        if branch_name == "develop" or "TEST_DICT" in os.environ:

            if release == "dev":
                # If the version is in dev, bump the dev version number
                LOGGER.info(
                    "repository_dispatch event: bumping dev version")
                bump_command = ["dev", "--tag"]
            else:
                # Otherwise, bump the patch version number
                LOGGER.info(
                    "repository_dispatch event: bumping patch version")
                bump_command = ["patch", "--tag"]
        else:
            LOGGER.info(
                "repository_dispatch event: only dev branch is supported for release"
            )
            return

        # Set credentials
        user = "Delfi-C3"
        email = "Delfi-C3@users.noreply.github.com"
        # Specify in username if the commit results from a test
        if "TEST_DICT" in os.environ:
            user = "Delfi-C3-TEST"
            email = "Delfi-C3-TEST@users.noreply.github.com"
        subprocess.run(["git", "config", "--global", "user.name", user])
        subprocess.run(["git", "config", "--global", "user.email", email])

        # Get current working directory
        cwd = os.getcwd()
        # Bump project version
        os.chdir(PROJECT_DIR)
        bumpversion.cli.main(bump_command)
        os.chdir(cwd)
        LOGGER.info("bumping version with command: %s", bump_command)

        # Get new version from version file in project repo open file
        with open(os.path.join(PROJECT_DIR, "version"), "r") as fp:
            new_version = fp.read().rstrip("\n")

        # Update version number in feedstock metadata
        new_var_vals = update_var_values(old_var_vals, new_version)
        VAR_SUBSTITUTE = [
            # These note where/how to find the version numbers
            ("recipe/meta.yaml", VERSION_REGEX, r'{% set version = "{}" %}', new_var_vals["version"]),
            ("recipe/meta.yaml", BUILD_REGEX, r'{% set build = "{}" %}', new_var_vals["build"]),
            ("recipe/meta.yaml", GIT_REV_REGEX, r'{% set git_rev = "v{}" %}', new_var_vals["git_rev"]),
            # Make sure that dev branch is used in conda configs
            # ("recipe/conda_build_config.yaml", TARGETS2_REGEX, r"- tudat-team {}", remap(branch_name)),
            # ("conda-forge.yml", TARGETS_REGEX, r'- [tudat-team, {}]', remap(branch_name))
        ]
        # Substitute all vars accordingly
        for file, regex, subst, val in VAR_SUBSTITUTE:
            path = os.path.join(FEEDSTOCK_DIR, file)
            # Read file
            with open(path, "r") as f:
                s = f.read()
                # Substitute
                s = regex.sub(subst.replace("{}", str(val)), s)
            # Write file    
            with open(path, "w") as f:
                f.write(s)

        # If in testing env, ask confirmation before pushing
        if "TEST_DICT" in os.environ:
            print("Last thing to do is to push to GitHub...")
            go_ahead = input("Do you want to still do so (even from this test environment)? (y/[n]): ")
            if go_ahead.lower() != "y":
                print("Exiting...")
                return

        # Push changes to GitHub
        for repo, dir in [(s_repository_feedstock, FEEDSTOCK_DIR),
                            (s_repository, PROJECT_DIR)]:
            # Add all files
            subprocess.run(["git", "add", "."], cwd=dir)

            # Commit with proper commit message
            subprocess.run(["git", "commit", "-m", commit_message], cwd=dir)

            # Get url to push to
            repo_auth_url = "https://%s@github.com/%s.git" % (os.environ["GH_TOKEN"], repo)

            # Push changes and tags
            subprocess.run(["git", "push", "--all", "-f", repo_auth_url], cwd=dir)
            subprocess.run(["git", "push", repo_auth_url, branch_name, "--tags"], cwd=dir)

def remap(key):
    map = {
        "develop": "dev",
        "master": "main"
    }
    if key in map:
        return map[key]
    return key

if __name__ == "__main__":
    # Set to true for testing (emulate repository dispatch event)
    test_env = True

    if not test_env:
        main()
    else:
        import shutil
        # Use export GH_TOKEN=<your token> to test with your own token.
        # Aslo see https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token
        if "GH_TOKEN" not in os.environ:
            raise ValueError("GH_TOKEN not set")

        gh = Github(os.environ["GH_TOKEN"])
        target_repo = "tudat-team/tudatpy"
        target_branch = "test_automation"
        
        # Get last commit from given branch
        repo = gh.get_repo(target_repo)
        branch = repo.get_branch(target_branch)
        # Convert commit time to datetime
        since = datetime.strptime(branch.commit.raw_data["commit"]["author"]["date"], "%Y-%m-%dT%H:%M:%SZ")
        # Check if the commit was less than 24hrs ago
        less_than_24_hrs = since < datetime.now() - timedelta(hours=24)
        
        # Print last commit infos
        print("Last commit was on branch '%s' by '%s' on %s (%s than 24hrs ago)" % (
            branch.name,
            branch.commit.raw_data["commit"]["author"]["name"],
            since,
            "more" if less_than_24_hrs else "less")
        )
        print("Commit message: %s" % branch.commit.raw_data["commit"]["message"])
        print("Commit url: https://github.com/%s/commit/%s" % (repo.full_name, branch.commit.sha))
        print()

        try:
            # Set environment variables to test automation on last commit
            os.environ["GITHUB_WORKSPACE"] = "./tmp"
            os.environ["TEST_DICT"] = json.dumps(dict(
                client_payload=dict(
                    ref_name=target_branch,
                    repository=target_repo,
                    sha=branch.commit.sha,
                    ref="refs/heads/%s"%target_branch,
                    ref_type="branch",
                    actor=branch.commit.raw_data["commit"]["author"]["name"],
                    event="push")
            ))
            os.environ["GITHUB_EVENT_NAME"] = "repository_dispatch"

            # Print environment variables
            print("The following environment variables are set:")
            print(" * GITHUB_WORKSPACE: %s" % os.environ["GITHUB_WORKSPACE"])
            print(" * TEST_DICT: %s" % os.environ["TEST_DICT"])
            print(" * GITHUB_EVENT_NAME: %s" % os.environ["GITHUB_EVENT_NAME"])
            print()

            # Run automation
            main()

            # Cleanup
            try:
                shutil.rmtree(os.environ["GITHUB_WORKSPACE"])
            except FileNotFoundError:
                pass
        
        except ValueError as e:
            print(e)
            shutil.rmtree(os.environ["GITHUB_WORKSPACE"])