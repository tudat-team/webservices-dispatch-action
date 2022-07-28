# webservices-dispatch-action
A GitHub action to abstract away tudat-team development details.

## Trigger
The code of [main.py](main.py) is triggered by actions present in the [tudat](https://github.com/tudat-team/tudat) and [tudatpy](https://github.com/tudat-team/tudatpy) GitHub repositories.

Every time a commit is pushed to the `main`, `master`, `develop`, or `feature/*` branch of one of these two repositories, the [repository-dispatch](https://github.com/peter-evans/repository-dispatch) action from peter-evans is used.

This action sends a payload to the [main.py](main.py) script that contains the repository name and references to the commit (from which the message, author, etc can be extracted).

## Actions
Once triggered, the [main.py](main.py) detects two event types:

1. Push to [tudat](https://github.com/tudat-team/tudat) or [tudatpy](https://github.com/tudat-team/tudatpy).
2. Nightly.

In case of a push event, the script looks for specific tags in the commit message. Currently, these can be `[CI]` or `[rerender]`.
If the `[rerender]` tag is detected, a rerender of the conda feedstock will be execute and, if any changes are detected, these will be pushed to the feedstock repository.
If the `[CI]` tag is detected, the version of `tudat` or `tudatpy` will be bumped in both the project and the feedstock repository, and a rerender will be executed.

In case of a nighty event, which should be automatically triggered every day, the script checks if the last change to the project were made less than 24hrs before. If so, the same action are executed than if a `[CI]` tag was present.

In both case, if changes are detected (from a version bump or a rerender), these are pushed to the feedstock repository. This means that the Azure pipeline of the given project will be triggered, triggering a build and release of the corresponding conda package.

Finally, it is worth nothing that this action makes the distinction between a push to `main`/`master`, and a push to `develop`/`dev`. Depending on which branch a commit was pushed to, changed will be pushed to the corresponding feedstock branch. This also means that the project version and conda package released will be the `dev` ones if a tag was detected in the `develop`/`dev` branch.

## Logs
The logs from the execution of this webservice can be accessed from the following page:
https://github.com/tudat-team/.github/actions/workflows/webservices.yml

## Repo structure

 * [Dockerfile](Dockerfile): This file contains the set of commands used to setup the system on which the code of the action is run. A good reference for this type of file can be found [in the docker documentation](https://docs.docker.com/engine/reference/builder). In essence, this file installs the required Python and Conda environment, and contains the command to run the [main.py](main.py) script, which runs the action.
 * [action.yml](action.yml): This file is the configuration of the GitHub action itself, using the syntax documented on [this page](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions). Most importantly, it contains a command to run docker with the aforementioned [Dockerfile](Dockerfile).
 * [main.py](main.py): This file contains the script used to decide wether to execute a rerender and/or a version bump + release. It extracts the commit information, pull the project and/or feedstock repository, make the required edits, then push the changes to the repositories.
 * [util.py](util.py): This file contains functions that, for now, are used to support the [main.py](main.py) script. These functions could in principle be re-used by different actions directly.

## Communication with other repositories

The full action is not run only trough the code from this repository.

For nightly releases, an action is setup in [tudat-team/.github/workflows/nightly.yml](https://github.com/tudat-team/.github/blob/main/.github/workflows/nightly.yml) that is automatically run every night at 3AM. This action is setup to trigger the `webservices-dispatch-action` from this repository for tudat and tudatpy. This trigger is made by first calling the [peter-evans/repository-dispatch](https://github.com/peter-evans/repository-dispatch) action, which then generates a payload and calls the `webservices-dispatch-action`.

Similarly, a push to for instance `tudatpy` will trigger the [inform](https://github.com/tudat-team/tudatpy/blob/develop/.github/workflows/inform.yml) actions that is configured inside of that repository. This action will, once again trough the use of the [peter-evans/repository-dispatch](https://github.com/peter-evans/repository-dispatch) action, call the `webservices-dispatch-action` of this repository.