import os
import json
import logging
import pprint
from github import Github
import pygit2

LOGGER = logging.getLogger(__name__)

def main():
    with open(os.environ["GITHUB_EVENT_PATH"], 'r') as fp:
        event_data = json.load(fp)
    event_name = os.environ['GITHUB_EVENT_NAME'].lower()

    github = Github(os.environ['GH_TOKEN'])
    github.get_repo(event_data['repository'])

    LOGGER.info('github event: %s', event_name)
    LOGGER.info('github event data:\n%s', pprint.pformat(event_data))

    if event_name == 'repository_dispatch':
        LOGGER.info('repository_dispatch event')

        # get feedstock of repository
        repo = github.get_repo(event_data['repository']+"-feedstock")

        # check if repo exists
        if repo is None:
            LOGGER.info('repository_dispatch event: feedstock repository not found')
            return

        ref_name = event_data['ref_name']
        cloned_repo = pygit2.clone_repository(repo.git_url, './tmp/feedstock')
        branch = cloned_repo.lookup_branch(ref_name)
        ref = cloned_repo.lookup_reference(branch.name)
        cloned_repo.checkout(ref)

if __name__ == "__main__":
    github = Github('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')
    repo = github.get_repo('tudat-team/tudat-resources-feedstock')

    cloned_repo = pygit2.clone_repository(repo.git_url, './here')
    branch = cloned_repo.lookup_branch('template')
    ref = cloned_repo.lookup_reference(branch.name)
    cloned_repo.checkout(ref)

    # print(repo.last_modified)
    # main()
