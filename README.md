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