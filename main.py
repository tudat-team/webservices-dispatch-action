import os
import json
import logging
from github import Github
import re
from util import *
import bumpversion.cli
from datetime import datetime, timedelta
import subprocess
import shutil


# Create logger with logging level set to all
LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main():
    # Two events:
    # 1. Push to tudat/tudatpy -> look for [CI]/[Rerender] tags in commit message and rerender and/or release if found
    # 2. Nightly -> rerender and release if last changes were less than 24hrs ago

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
        tags_found, commit_message = get_commit_tags(project_repo, payload["sha"], supported_tags=["ci", "rerender"])
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
        release = was_branch_last_commit_recent(project_repo, branch_name, time_treshold=timedelta(hours=22))
        commit_message = "BOT: Changes detected in project, nightly release 🌃"

    # Quit if the event is not a push nor a nightly
    else:
        return

    # Create path for feedstock and project repos locally
    FEEDSTOCK_DIR, PROJECT_DIR = [os.path.join(os.environ["GITHUB_WORKSPACE"], repo_full_name.split("/")[-1]) for repo_full_name in [s_repository_feedstock, s_repository]]

    # Rerender the feedstock
    if rerender:
        LOGGER.info("starting rerender")

        # Clone the feedstock repo at its correct branch
        LOGGER.info("cloning feedstock repository")
        clone_repo(feedstock_repo.clone_url, FEEDSTOCK_DIR, branch_name, os.environ['GH_TOKEN'])
        
        # Make sure conda exists
        os.system("conda --version > /dev/null")
        if os.system("conda --version > /dev/null") != 0:
            LOGGER.error("conda not found")
            return

        # Make sure conda is up to date
        LOGGER.info("updating conda")
        os.system("conda update -n base -c defaults conda -y")

        # Make sure conda-smithy is installed and up-to-date
        LOGGER.info("updating conda-smithy")
        os.system("conda install -n base -c conda-forge conda-smithy -y")

        # # Make sure that dev branch is used in conda configs
        # TARGETS_REGEX = re.compile(r"-\s+\[(?P<channel>[\w,-].+)\, \s+(?P<subchannel>[\w,-]+)]")
        # TARGETS2_REGEX = re.compile(r"(?<=channel_targets:\n\s\s)-\s+(?P<targets>[\s,\w,-]+)")
        # VAR_SUBSTITUTE = []
        # VAR_SUBSTITUTE.append(("recipe/conda_build_config.yaml", TARGETS2_REGEX, r"- tudat-team {}", remap(branch_name)))
        # VAR_SUBSTITUTE.append(("conda-forge.yml", TARGETS_REGEX, r'- [tudat-team, {}]', remap(branch_name)))
        # substitute_vars_in_file(VAR_SUBSTITUTE, FEEDSTOCK_DIR)

        # Run conda-smithy rerender
        LOGGER.info("running conda smithy rerender")
        r = subprocess.Popen(["conda", "smithy", "rerender"], cwd=FEEDSTOCK_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Get the new commit message
        rerender_output = r.communicate()[-1].decode("utf-8")
        rerender_commit_message = None
        for line in rerender_output.split("\n"):
            if line.strip().startswith('git commit -m "'):
                rerender_commit_message = line.strip().split('"')[1]
                break
        if rerender_commit_message is None:
            LOGGER.error("could not find commit message in rerender output. Feedstock most likely already up-to-date.")
            LOGGER.info("conda smithy rerender output was:\n%s", rerender_output)
        else:
            LOGGER.info("conda-smithy rerender commit message: '%s'", rerender_commit_message)
            # Commit changes
            subprocess.run(["git", "commit", "-m", rerender_commit_message], cwd=FEEDSTOCK_DIR)

    # Release a conda package
    if release:
        LOGGER.info("starting release")

        # Clone the feedstock and project repos at their correct branch
        if not rerender:
            # If rerender was triggered, the feedstock repo is already cloned
            LOGGER.info("cloning feedstock repository")
            clone_repo(feedstock_repo.clone_url, FEEDSTOCK_DIR, branch_name, os.environ['GH_TOKEN'])
        LOGGER.info('cloning project repository')
        clone_repo(project_repo.clone_url, PROJECT_DIR, branch_name, os.environ['GH_TOKEN'])

        # Get project version number
        version = get_project_version(PROJECT_DIR)
        if version is None:
            return
        
        # Retrieve version, build, and rev values from previous feedstock metadata
        version_types = ["version", "build", "git_rev"]
        VAR_RETRIEVE = [(v_type, "recipe/meta.yaml", re.compile('{%\s*set\s*' + v_type + '\s*=\s*"([^"]*)"\s*%}')) for v_type in version_types]
        old_var_vals = get_var_values(VAR_RETRIEVE, FEEDSTOCK_DIR)
        LOGGER.info("old_var_vals: %s", pprint.pformat(old_var_vals))
        LOGGER.info("version: %s", version)
        # Make sure the version is the same as the one in the feedstock
        assert old_var_vals["version"] == version, "version mismatch"

        # Trigger release if branch is develop, or if the environment is test
        if branch_name == "develop" or "TEST_DICT" in os.environ:

            if remap(branch_name) == "dev" or "TEST_DICT" in os.environ:
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
        new_version = get_project_version(PROJECT_DIR)
        if new_version is None:
            return

        # Update version number in feedstock metadata
        new_var_vals = update_var_values(old_var_vals, new_version)
        VAR_SUBSTITUTE = [(
            "recipe/meta.yaml",
            re.compile('{%\s*set\s*' + v_type + '\s*=\s*"([^"]*)"\s*%}'),
            '{% set ' + v_type + ' = "v{}" %}' if v_type == "git_rev" else '{% set ' + v_type + ' = "{}" %}',
            new_var_vals[v_type]
        ) for v_type in version_types]

        # Substitute all vars accordingly
        substitute_vars_in_file(VAR_SUBSTITUTE, FEEDSTOCK_DIR)

    # If in testing env, ask confirmation before pushing
    if "TEST_DICT" in os.environ:
        print("Last thing to do is to push to GitHub...")
        go_ahead = input("Do you want to still do so (even from this test environment)? (y/[n]): ")
        if go_ahead.lower() != "y":
            print("Exiting...")
            return

    # Push changes to GitHub
    to_push = []
    if rerender and rerender_commit_message is not None:
        to_push.append((s_repository_feedstock, FEEDSTOCK_DIR))
    if release:
        to_push.append((s_repository, PROJECT_DIR))
    for repo, dir in to_push:
        push_all_to_github(repo, branch_name, dir, commit_message)

def remap(key):
    map = {
        "develop": "dev",
        "master": "main"
    }
    if key in map:
        return map[key]
    return key

def simulate_repository_dispatch():
    """
    Simulate a repository dispatch event as if main() was running in production.
    """
    # Use export GH_TOKEN=<your token> to test with your own token.
    # Also see https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token
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

if __name__ == "__main__":
    # Set to true for testing (emulate repository dispatch event)
    test_env = False
    if test_env:
        try:
            simulate_repository_dispatch()
        except ValueError as e:
            print("Warning:", e)
            print("This directory will be removed, and the script run again.")
            shutil.rmtree(os.environ["GITHUB_WORKSPACE"])
            simulate_repository_dispatch()
    else:
        main()